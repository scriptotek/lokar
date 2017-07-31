# coding=utf-8
from __future__ import unicode_literals

import argparse
import getpass
import colorlog
import logging.handlers
import re
import os
import sys
from io import open  # pylint: disable=redefined-builtin

import yaml
from raven import Client
from six import binary_type

from . import __version__
from .vocabulary import Vocabulary
from .alma import Alma
from .concept import Concept
from .job import Job
from .sru import SruClient

raven_client = None

log = logging.getLogger()
log.setLevel(logging.INFO)
logging.getLogger('requests').setLevel(logging.WARNING)
console_handler = logging.StreamHandler()
console_handler.setFormatter(colorlog.ColoredFormatter(
    '%(asctime)s %(log_color)s%(levelname)-8s%(reset)s %(message)s',
    datefmt='%Y-%m-%d %H:%I:%S',
    reset=True,
    log_colors={
        'DEBUG':    'cyan',
        'INFO':     'green',
        'WARNING':  'red',
        'ERROR':    'red',
        'CRITICAL': 'red,bg_white',
    }))
log.addHandler(console_handler)

SUPPORTED_TAGS = ['084', '648', '650', '651', '655']


def parse_args(args, default_env=None):
    parser = argparse.ArgumentParser(prog='almar', description='''
            Edit or remove subject fields in Alma catalog records.
            Supported fields: {}
            '''.format(', '.join(SUPPORTED_TAGS)))
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    parser.add_argument('-e', '--env', dest='env', nargs='?',
                        help='Environment from config file. Default: {}'.format(default_env or '(none)'),
                        default=default_env)

    parser.add_argument('-d', '--dry_run', dest='dry_run', action='store_true',
                        help='Dry run without doing any edits.')

    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='Show more output')

    parser.add_argument('-n', '--non-interactive', dest='non_interactive', action='store_true',
                        help='Non-interactive mode. Always use defaults rather than asking.')

    parser.add_argument('--diffs', dest='show_diffs', action='store_true',
                        help='Show diffs before saving.')

    subparsers = parser.add_subparsers(title='subcommands')

    # Create parser for the "move" command
    parser_move = subparsers.add_parser('rename', help='Rename/move term')
    parser_move.add_argument('term', nargs=1, help='Term to search for')
    parser_move.add_argument('new_term', nargs=1, default='', help='Replacement term')
    parser_move.add_argument('new_term2', nargs='?', default='', help='Second replacement term')
    parser_move.set_defaults(action='rename')

    # Create parser for the "delete" command
    parser_del = subparsers.add_parser('delete', help='Delete term')
    parser_del.add_argument('term', nargs=1, help='Term to delete')
    parser_del.set_defaults(action='delete')

    # Create parser for the "interactive" command
    parser_int = subparsers.add_parser('interactive', help='Interactive reclassification')
    parser_int.add_argument('term', nargs=1, help='Term to search for')
    parser_int.add_argument('new_terms', nargs='+', default='', help='Replacement terms')
    parser_int.set_defaults(action='interactive')

    # Create parser for the "list" command
    parser_list = subparsers.add_parser('list', help='List documents')
    parser_list.add_argument('term', nargs=1, help='Term to search for')
    parser_list.add_argument('--titles', dest='show_titles', action='store_true', help='Show titles')
    parser_list.add_argument('--subjects', dest='show_subjects', action='store_true', help='Show subject fields')
    parser_list.set_defaults(action='list')

    # Parse
    args = parser.parse_args(args)

    if 'action' not in args:
        parser.error('No action specified')

    if args.env is not None:
        args.env = args.env.strip()

    args.term = args.term[0]

    if args.action in ['delete', 'list']:
        args.new_terms = []
    elif args.action == 'rename':
        args.new_terms = [args.new_term[0]]
        if args.new_term2 != '':
            args.new_terms.append(args.new_term2)

    def normalize_arg(arg):
        if isinstance(arg, binary_type):
            return arg.decode('utf-8')
        return arg

    args.term = normalize_arg(args.term)
    args.env = normalize_arg(args.env)
    args.new_terms = [normalize_arg(x) for x in args.new_terms]

    return args


def get_concept(term, vocabulary, default_tag='650', default_term=None):
    match = re.match('^({})$'.format('|'.join(SUPPORTED_TAGS)), term)
    if match:
        if default_term is None:
            raise RuntimeError('No source term specified')
        return Concept(default_term, vocabulary, match.group(1))

    match = re.match('^({}) (.+)$'.format('|'.join(SUPPORTED_TAGS)), term)
    if match:
        return Concept(match.group(2), vocabulary, match.group(1))

    return Concept(term, vocabulary, default_tag)


def job_args(config=None, args=None):
    vocabulary = Vocabulary(config['vocabulary']['marc_code'],
                            config['vocabulary'].get('id_service'),
                            config['vocabulary'].get('marc_prefix', ''))

    source_concept = get_concept(args.term, vocabulary)
    target_concepts = []
    list_options = {}

    if args.action == 'rename':
        target_concepts.append(get_concept(args.new_terms[0], vocabulary,
                                           default_term=source_concept.term,
                                           default_tag=source_concept.tag))

        if len(args.new_terms) > 1:
            target_concepts.append(get_concept(args.new_terms[1], vocabulary,
                                               default_tag=source_concept.tag))

    elif args.action in ['interactive', 'list']:
        target_concepts = [
            get_concept(term, vocabulary, default_tag=source_concept.tag) for term in args.new_terms
        ]

    if args.action == 'list':
        list_options['show_titles'] = args.show_titles
        list_options['show_subjects'] = args.show_subjects

    return {
        'action': args.action,
        'source_concept': source_concept,
        'target_concepts': target_concepts,
        'list_options': list_options,
    }


def get_config_file():
    possible_file_locations = ['./almar.yml', './lokar.yml', os.path.expanduser('~/.almar.yml')]

    for filename in possible_file_locations:
        if os.path.exists(filename):
            return filename


def main(config=None, args=None):
    global raven_client
    filename = get_config_file()
    if filename is None:
        log.error('Could not find "almar.yml" configuration file. See https://github.com/scriptotek/almar for help.')
        sys.exit(1)

    try:
        with config or open(filename) as file:
            config = yaml.load(file)
    except IOError:
        log.error('Could not read configuration file "%s"', filename)
        sys.exit(1)

    username = getpass.getuser()
    log.info('Running as %s', username)
    try:
        if config.get('sentry') is not None:
            raven_client = Client(config['sentry']['dsn'])
            raven_client.context.merge({'user': {
                'username': username
            }})

        args = parse_args(args or sys.argv[1:], config.get('default_env'))
        jargs = job_args(config, args)

        if args.verbose:
            log.setLevel(logging.DEBUG)

        if not args.dry_run:
            file_handler = logging.FileHandler('almar.log')
            file_handler.setFormatter(logging.Formatter(
                '[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%I:%S'))
            file_handler.setLevel(logging.INFO)
            log.addHandler(file_handler)

        def get_env(config, args):
            if args.env is None:
                log.error('No environment specified and no default environment found in configuration file')
                sys.exit(1)

            for env in config.get('env', []):
                if env['name'] == args.env:
                    return env

            log.error('Environment "%s" not found in configuration file', args.env)
            sys.exit(1)

        env = get_env(config, args)

        sru = SruClient(env['sru_url'], args.env)
        alma = Alma(env['api_region'], env['api_key'], args.env)

        job = Job(sru=sru, alma=alma, **jargs)
        job.dry_run = args.dry_run
        job.interactive = not args.non_interactive
        job.verbose = args.verbose
        job.show_diffs = args.show_diffs

        job.start()
        log.info('Job complete')

    except Exception:  # # pylint: disable=broad-except
        if raven_client is not None:
            raven_client.captureException()
        log.exception('Uncaught exception:')


if __name__ == '__main__':
    main()