# coding=utf-8
from __future__ import unicode_literals
from future.utils import python_2_unicode_compatible
from collections import OrderedDict
import logging
import six
from lxml import etree

from .concept import Concept
from .util import parse_xml, ANY_VALUE, normalize_term

log = logging.getLogger(__name__)


class Task(object):
    """
    Task class from which the other task classes inherit.
    """

    def __init__(self, source, targets=None):
        targets = targets or []
        assert isinstance(source, Concept)
        assert type(targets) == list
        for target in targets:
            assert isinstance(target, Concept)
        self.source = source
        self.targets = targets

    def make_query(self, target=None):
        query = OrderedDict([
            ('2', {'search': self.source.sf['2']})
        ])
        for n in ['a', 'b', 'x', 'y', 'z']:
            query[n] = {'search': self.source.sf.get(n)}
            if target is not None:
                query[n]['replace'] = target.sf.get(n)

        if target is not None and target.sf.get('0') is not None:
            query['0'] = {'search': ANY_VALUE, 'replace': target.sf.get('0')}

        return query

    def match(self, marc_record):
        query = self.make_query()

        return len(marc_record.fields(self.source.tag, query)) != 0

    @staticmethod
    def get_simple_subject_repr(field, subfields='abxyz'):
        subfields = list(subfields)
        key = [field.node.get('tag')]
        for subfield in field.node.findall('subfield'):
            if subfield.get('code') in subfields:
                key.append('$%s %s' % (subfield.get('code'), normalize_term(subfield.text)))

        return ' '.join(key)

    def remove_duplicates(self, marc_record, tag, query):
        dups = 0
        keys = []

        query2 = {}
        for k, v in query.items():
            if v is None:
                query2[k] = None
            elif six.text_type(v) == v:
                query2[k] = v
            elif 'replace' in v:
                query2[k] = v['replace']
            else:
                query2[k] = v['search']

        for field in marc_record.fields(tag, query2):
            key = self.get_simple_subject_repr(field)
            if key in keys:
                marc_record.remove_field(field)
                log.info('Term was already present on the record: %s', key)
                dups += 1
                continue
            keys.append(key)

        return dups


@python_2_unicode_compatible
class ReplaceTask(Task):
    """
    Replace a subject access or classification number field with another one in
    any given MARC record.
    """

    def __init__(self, source, target, ignore_extra_components=False):
        super(ReplaceTask, self).__init__(source, [target])
        self.ignore_extra_components = ignore_extra_components

    def make_component_query(self, target=None):
        """
        Match the defined subfields of the source concept (like $a), while
        ignoring any additional subfields (like $x).
        """
        query = OrderedDict([
            ('2', {'search': self.source.sf.get('2')})
        ])
        for n in ['a', 'b', 'x', 'y', 'z']:
            if self.source.sf.get(n) is not None:
                query[n] = {'search': self.source.sf.get(n)}
                if target is not None:
                    query[n]['replace'] = target.sf.get(n)

        return query

    def __str__(self):
        s = []
        t = []
        for k, v in self.make_query(self.targets[0]).items():
            if k != '2':
                if v.get('search') is not None:
                    s.append('${} {}'.format(k, v['search']))
                if v.get('replace') is not None:
                    t.append('${} {}'.format(k, v['replace']))

        return 'Replace {} with {} in {} $2 {}'.format(' '.join(s),
                                                       ' '.join(t),
                                                       self.source.tag,
                                                       self.source.sf.get('2'))

    def match(self, marc_record):
        # If the inexact query matches, we don't need to check the exact one
        if self.ignore_extra_components:
            query = self.make_component_query()
        else:
            query = self.make_query()

        return len(marc_record.fields(self.source.tag, query)) != 0

    def run(self, marc_record):
        modified = 0
        queries = [self.make_query(self.targets[0])]
        if self.ignore_extra_components:
            queries.append(self.make_component_query(self.targets[0]))
        for query in queries:
            for field in marc_record.fields(self.source.tag, query):
                modified += field.update(query)

        self.remove_duplicates(marc_record, self.source.tag, self.make_query(self.targets[0]))

        return modified


@python_2_unicode_compatible
@python_2_unicode_compatible
class DeleteTask(Task):
    """
    Delete a subject access or classification number field from any given MARC record.
    """

    def __str__(self):
        return 'Delete {} {} $2 {}'.format(self.source.tag, self.source, self.source.sf['2'])

    def run(self, marc_record):
        query = self.make_query()
        removed = 0
        for field in marc_record.fields(self.source.tag, query):
            marc_record.remove_field(field)
            removed += 1

        return removed
        # Open question: should we also remove strings where sf['a'] is a component???


@python_2_unicode_compatible
class AddTask(Task):
    """
    Add a new subject access or classification number field to any given MARC record.
    """

    def __str__(self):
        return 'Add {} {} $2 {}'.format(self.source.tag, self.source, self.source.sf['2'])

    def match(self, marc_record):
        return False  # This task will only be run if some other task matches the record.

    def run(self, marc_record):
        new_field = parse_xml("""
            <datafield tag="{tag}" ind1=" " ind2="7">
                <subfield code="a">{term}</subfield>
                <subfield code="2">{vocabulary}</subfield>
            </datafield>
        """.format(term=self.source.sf['a'], tag=self.source.tag, vocabulary=self.source.sf['2']))

        if self.source.sf.get('0') is not None:
            el = etree.Element('subfield', code="0")
            el.text = self.source.sf['0']
            new_field.append(el)

        if self.source.sf.get('x') is not None:
            el = etree.Element('subfield', code="x")
            el.text = self.source.sf['x']
            new_field.append(el)

        existing_subjects = marc_record.fields(self.source.tag, {
            '2': {'search': self.source.sf['2']},
        })
        if len(existing_subjects) > 0:
            idx = marc_record.el.index(existing_subjects[-1].node)
            marc_record.el.insert(idx + 1, new_field)
        else:
            marc_record.el.append(new_field)

        self.remove_duplicates(marc_record, self.source.tag, {
            '2': self.source.sf.get('2'),
            'a': self.source.sf.get('a'),
            'x': self.source.sf.get('x'),
        })

        return 1


@python_2_unicode_compatible
class MoveTask(Task):
    """
    Move a subject access or classification number field to another MARC tag
    (e.g. from 650 to 648) in any given MARC record.
    """

    def __init__(self, source, dest_tag):
        super(MoveTask, self).__init__(source)
        self.dest_tag = dest_tag

    def __str__(self):
        term = '$a {}'.format(self.source.sf.get('a'))
        if self.source.sf.get('x') is not None:
            term += ' $x {}'.format(self.source.sf.get('x'))
        return 'Move {} {} $2 {} to {}'.format(self.tag, term, self.source.sf.get('2'), self.dest_tag)

    def run(self, marc_record):
        query = self.make_query()

        moved = 0
        for field in marc_record.fields(self.source.tag, query):
            field.set_tag(self.dest_tag)
            moved += 1

        self.remove_duplicates(marc_record, self.dest_tag, query)

        return moved
