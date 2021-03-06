"""
MongoDB Storage and Migrations for Policies.
"""

import logging
import copy
from abc import ABCMeta

import bson.json_util as b_json
from pymongo.errors import DuplicateKeyError
import jsonpickle.tags

from ..storage.abc import Storage
from ..storage.migration import Migration, MigrationSet
from ..exceptions import PolicyExistsError, UnknownCheckerType, Irreversible
from ..policy import Policy
from ..rules.base import Rule
from ..checker import StringExactChecker, StringFuzzyChecker, RegexChecker, RulesChecker
from ..policy import TYPE_STRING_BASED, TYPE_RULE_BASED


DEFAULT_COLLECTION = 'vakt_policies'
DEFAULT_MIGRATION_COLLECTION = 'vakt_policies_migration_version'

log = logging.getLogger(__name__)


class MongoStorage(Storage):
    """Stores all policies in MongoDB"""

    def __init__(self, client, db_name, collection=DEFAULT_COLLECTION):
        self.client = client
        self.database = self.client[db_name]
        self.collection = self.database[collection]
        self.condition_fields = [
            'actions',
            'subjects',
            'resources',
        ]

    def add(self, policy):
        try:
            self.collection.insert_one(self.__prepare_doc(policy))
        except DuplicateKeyError:
            log.error('Error trying to create already existing policy with UID=%s.', policy.uid)
            raise PolicyExistsError(policy.uid)
        log.info('Added Policy: %s', policy)

    def get(self, uid):
        ret = self.collection.find_one(uid)
        if not ret:
            return None
        return self.__prepare_from_doc(ret)

    def get_all(self, limit, offset):
        self._check_limit_and_offset(limit, offset)
        cur = self.collection.find(limit=limit, skip=offset)
        return self.__feed_policies(cur)

    def find_for_inquiry(self, inquiry, checker=None):
        q_filter = self._create_filter(inquiry, checker)
        cur = self.collection.find(q_filter)
        return self.__feed_policies(cur)

    def update(self, policy):
        uid = policy.uid
        self.collection.update_one(
            {'_id': uid},
            {"$set": self.__prepare_doc(policy)},
            upsert=False)
        log.info('Updated Policy with UID=%s. New value is: %s', uid, policy)

    def delete(self, uid):
        self.collection.delete_one({'_id': uid})
        log.info('Deleted Policy with UID=%s.', uid)

    def _create_filter(self, inquiry, checker):
        """
        Returns proper query-filter based on the checker type.
        """
        if isinstance(checker, StringFuzzyChecker):
            return self.__string_query_on_conditions('$regex', lambda field: getattr(inquiry, field))
        elif isinstance(checker, StringExactChecker):
            return self.__string_query_on_conditions('$eq', lambda field: getattr(inquiry, field))
            # We do not use Reverse-regexp match since it's not implemented yet in MongoDB.
            # Doing it via Javascript function gives no benefits over Vakt final Guard check.
            # See: https://jira.mongodb.org/browse/SERVER-11947
        elif isinstance(checker, RegexChecker):
            return {'type': TYPE_STRING_BASED}
        elif isinstance(checker, RulesChecker):
            return {'type': TYPE_RULE_BASED}
        elif not checker:
            return {}
        else:
            log.error('Provided Checker type is not supported.')
            raise UnknownCheckerType(checker)

    def __string_query_on_conditions(self, operator, get_value):
        """
        Construct MongoDB query.
        """
        conditions = [
            {'type': TYPE_STRING_BASED}
        ]
        for field in self.condition_fields:
            conditions.append(
                {
                    field: {
                        '$elemMatch': {
                            operator: get_value(field.rstrip('s'))
                        }
                    }
                }
            )
        return {"$and": conditions}

    @staticmethod
    def __prepare_doc(policy):
        """
        Prepare Policy object as a document for insertion.
        """
        # todo - add dict inheritance
        doc = b_json.loads(policy.to_json())
        doc['_id'] = policy.uid
        return doc

    @staticmethod
    def __prepare_from_doc(doc):
        """
        Prepare Policy object as a return from MongoDB.
        """
        # todo - add dict inheritance
        del doc['_id']
        return Policy.from_json(b_json.dumps(doc))

    def __feed_policies(self, cursor):
        """
        Yields Policies from the given cursor.
        """
        for doc in cursor:
            yield self.__prepare_from_doc(doc)


##############
# Migrations #
##############

class MongoMigrationSet(MigrationSet):
    """
    Migrations Collection for MongoStorage
    """
    def __init__(self, storage, collection=DEFAULT_MIGRATION_COLLECTION):
        self.storage = storage
        self.collection = self.storage.database[collection]
        self.key = 'version'
        self.filter = {'_id': 'migration_version'}

    def migrations(self):
        return [
            Migration0To1x1x0(self.storage),
            Migration1x1x0To1x1x1(self.storage),
            Migration1x1x1To1x2x0(self.storage),
        ]

    def save_applied_number(self, number):
        self.collection.update_one(self.filter, {'$set': {self.key: number}}, upsert=True)

    def last_applied(self):
        data = self.collection.find_one(self.filter)
        if data:
            return int(data[self.key])
        return 0


class MongoMigration(Migration, metaclass=ABCMeta):
    """
    Mongo DB migration abstract base class
    """
    def _each_doc(self, processor):
        """
        Iterate each doc in the DB and run processor function with it
        """
        failed_policies = []
        storage = getattr(self, 'storage')
        cur = storage.collection.find()
        for doc in cur:
            try:
                log.info('Trying to migrate Policy with UID: %s', doc['uid'])
                new_doc = processor(doc)
                storage.collection.replace_one({'_id': new_doc['uid']}, new_doc)
                log.info('Policy with UID: %s was migrated', doc['uid'])
            except Irreversible as e:
                log.warning('Irreversible Policy. %s. Mongo doc: %s', e, doc)
                failed_policies.append(doc)
            except Exception as e:
                log.exception('Unexpected exception occurred while migrating Policy: %s', doc)
                failed_policies.append(doc)
        if failed_policies:
            msg = "\n".join([
                'Migration was unable to convert some Policies, but they were left in the database as-is. ' +
                'They might be not automatically convertible, custom ones, malformed JSON docs.',
                'You must convert them manually or delete entirely. See above log output for details of migration.',
                'Mongo IDs of failed Policies are: %s' % [p['_id'] for p in failed_policies]
            ])
            log.error(msg)


class Migration0To1x1x0(MongoMigration):
    """
    Migration between versions 0 and 1.1.0
    """

    def __init__(self, storage):
        self.storage = storage
        self.index_name = lambda i: i + '_idx'
        self.multi_key_indices = [
            'actions',
            'subjects',
            'resources',
        ]

    @property
    def order(self):
        return 1

    def up(self):
        # MongoDB automatically creates a multikey index if any indexed field is an array;
        # https://docs.mongodb.com/manual/core/index-multikey/#create-multikey-index
        for field in self.multi_key_indices:
            self.storage.collection.create_index(field, name=self.index_name(field))

    def down(self):
        for field in self.multi_key_indices:
            self.storage.collection.drop_index(self.index_name(field))


class Migration1x1x0To1x1x1(MongoMigration):
    """
    Migration between versions 1.1.0 and 1.1.1
    """

    def __init__(self, storage):
        self.storage = storage
        self._type_marker = jsonpickle.tags.OBJECT

    @property
    def order(self):
        return 2

    def up(self):
        def process(doc):
            """Processor for up"""
            doc_to_save = copy.deepcopy(doc)
            rules_to_save = {}
            for name, rule_str in doc['rules'].items():
                rule = b_json.loads(rule_str)
                rule_to_save = {self._type_marker: rule['type']}
                rule_to_save.update(rule['contents'])
                rules_to_save[name] = rule_to_save
            doc_to_save['rules'] = rules_to_save
            return doc_to_save
        self._each_doc(processor=process)

    def down(self):
        def process(doc):
            """Processor for down"""
            doc_to_save = copy.deepcopy(doc)
            rules_to_save = {}
            for name, rule in doc['rules'].items():
                rule_type = rule[self._type_marker]
                rule_contents = rule.copy()
                del rule_contents[self._type_marker]
                rule_to_save = {'type': rule_type, 'contents': {}}
                # check if we are dealing with 3-rd party or custom rules
                if not rule_type.startswith('vakt.rules.'):
                    for value in rule_contents.values():
                        # if rule has non-primitive data as its contents - we can't revert it to 1.1.0
                        if isinstance(value, (dict, Rule)) and jsonpickle.tags.RESERVED.intersection(value.keys()):
                            raise Irreversible('Custom rule class contains non-primitive data %s' % value)
                # vakt's own RegexMatchRule couldn't be stored in mongo because is has non-primitive data,
                # so it's impossible to put it to storage if we revert time back to 1.1.0
                elif rule_type == 'vakt.rules.string.RegexMatchRule':
                    raise Irreversible('vakt.rules.string.RegexMatchRule could not be stored in v1.1.0')
                rule_to_save['contents'].update(rule_contents)
                rules_to_save[name] = b_json.dumps(rule_to_save, sort_keys=True)
            # report or save document
            doc_to_save['rules'] = rules_to_save
            return doc_to_save
        self._each_doc(processor=process)


class Migration1x1x1To1x2x0(MongoMigration):
    """
    Migration between versions 1.1.1 and 1.2.0.
    What it does:
    - Adds index for `type` field
    - Updates Policies to:
        - have an appropriate type (all existing policies will become of a string-based type)
        - have 'context' attribute instead of 'rules' attribute
    """

    def __init__(self, storage):
        self.storage = storage
        self.type_field = 'type'
        self.type_index = 'type_idx'
        self.rules_rename = {
            'vakt.rules.string.StringEqualRule': 'vakt.rules.string.Equal',
            'vakt.rules.string.RegexMatchRule': 'vakt.rules.string.RegexMatch',
            'vakt.rules.string.StringPairsEqualRule': 'vakt.rules.string.PairsEqual',
            'vakt.rules.net.CIDRRule': 'vakt.rules.net.CIDR',
            'vakt.rules.inquiry.SubjectEqualRule': 'vakt.rules.inquiry.SubjectEqual',
            'vakt.rules.inquiry.ActionEqualRule': 'vakt.rules.inquiry.ActionEqual',
            'vakt.rules.inquiry.ResourceInRule': 'vakt.rules.inquiry.ResourceIn',
        }

    @property
    def order(self):
        return 3

    def up(self):
        def process(doc):
            """Processor for up"""
            doc['type'] = TYPE_STRING_BASED
            for rule in doc['rules'].values():
                rule_type = rule[jsonpickle.tags.OBJECT]
                for old, new in self.rules_rename.items():
                    if rule_type == old:
                        rule[jsonpickle.tags.OBJECT] = new
                        break
            doc['context'] = doc['rules']
            del doc['rules']
            return doc
        self.storage.collection.create_index(self.type_field, name=self.type_index)
        self._each_doc(processor=process)

    def down(self):
        def process(doc):
            """Processor for down"""
            if doc['type'] != TYPE_STRING_BASED:
                raise Irreversible('Policy is not of a string-based type, so not supported in < v1.2.0')
            for rule in doc['context'].values():
                rule_type = rule[jsonpickle.tags.OBJECT]
                for old, new in self.rules_rename.items():
                    if rule_type == new:
                        rule[jsonpickle.tags.OBJECT] = old
                        break
                if rule_type.startswith('vakt.rules.list') or \
                        rule_type.startswith('vakt.rules.logic') or \
                        rule_type.startswith('vakt.rules.operator') or \
                        rule_type in ['vakt.rules.string.StartsWith',
                                      'vakt.rules.string.EndsWith',
                                      'vakt.rules.string.Contains']:
                    raise Irreversible('Context contains rule that exist only in >= v1.2.0: %s' % rule)
            doc['rules'] = doc['context']
            del doc['context']
            del doc['type']
            return doc
        self.storage.collection.drop_index(self.type_index)
        self._each_doc(processor=process)
