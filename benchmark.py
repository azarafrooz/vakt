import random
import uuid
import timeit
import argparse
import contextlib
from functools import partial

from pymongo import MongoClient

from vakt.storage.memory import MemoryStorage
from vakt.storage.mongo import MongoStorage
from vakt.rules.net import CIDR
from vakt.effects import DENY_ACCESS, ALLOW_ACCESS
from vakt.policy import Policy
from vakt.checker import RegexChecker, RulesChecker
from vakt.guard import Guard, Inquiry
from vakt.rules import operator, logic, list


# Globals
LINE_LEN = 80
overall_policies_created = 0
similar_regexp_policies_created = 0


# Define and parse possible arguments
parser = argparse.ArgumentParser(description='Run vakt benchmark.')
parser.add_argument('-n', '--number', dest='policies_number', nargs='?', type=int, default=100000,
                    help='number of policies to create in DB (default: %(default)d)')
parser.add_argument('-d', '--storage', choices=('mongo', 'memory'), default='memory',
                    help='type of storage (default: %(default)s)')
parser.add_argument('-c', '--checker', choices=('regex', 'rules', 'exact', 'fuzzy'), default='regex',
                    help='type of checker (default: %(default)s)')

regex_group = parser.add_argument_group('regex policy related')
regex_group.add_argument('--regexp', action='store_false', default=True,
                         help='should Policies be defined without Regex syntax? (default: %(default)s)')
regex_group.add_argument('--same', type=int, default=0,
                         help='number of similar regexps in Policy')
regex_group.add_argument('--cache', type=int,
                         help="number of LRU-cache for RegexChecker (default: RegexChecker's default cache-size)")

ARGS = parser.parse_args()


def rand_string():
    return ''.join([chr(random.randint(97, 122)) for _ in range(0, 10)])


def rand_true():
    return bool(random.getrandbits(1))


def gen_id():
    return str(uuid.uuid4())


def gen_regexp():
    a, b = [rand_string() for _ in range(2)]
    return '<[\d]{3}[%s]*>' % a, '<[%s]{2}>' % b


def gen_policy():
    if ARGS.checker == 'rules':
        return Policy(
            uid=gen_id(),
            effect=ALLOW_ACCESS if rand_true() else DENY_ACCESS,
            subjects=[
                {
                    'name': logic.Or(operator.Eq('Nicky'), operator.Eq('Nick')),
                    'stars': logic.And(
                        operator.Greater(random.randint(-1000, -1)),
                        operator.Less(random.randint(1000, 3000)),
                        operator.Eq(900)
                    ),
                    'status': operator.Eq('registered')
                },
            ],
            resources=(
                {
                    'method': list.AnyInList(['get', 'post', 'delete']),
                    'path': list.NotInList(['org/custom', 'vacations/pending', 'должность/повысить']),
                    'id': operator.Eq(rand_string())
                },
                {
                    'method': operator.Eq('violate'),
                }
            ),
            actions=(
                {'before': operator.Eq('foo')},
                {'after': list.InList([rand_string(), rand_string(), rand_string()])},
            ),
            context={
                'ip': CIDR('127.0.0.1'),
            },
        )
    else:
        global similar_regexp_policies_created
        static_subjects = gen_regexp()
        if ARGS.regexp:
            if similar_regexp_policies_created < ARGS.same:
                subjects = static_subjects
                similar_regexp_policies_created += 1
            else:
                subjects = gen_regexp()
        else:
            subjects = (rand_string(), rand_string())
        return Policy(
            uid=gen_id(),
            effect=ALLOW_ACCESS if rand_true() else DENY_ACCESS,
            subjects=subjects,
            resources=('library:books:<.+>', 'office:magazines:<.+>'),
            actions=['<' + rand_string() + '|' + rand_string() + '>'],
            context={
                'ip': CIDR('127.0.0.1'),
            },
        )


def get_checker():
    if ARGS.checker == 'rules':
        return RulesChecker()
    return RegexChecker(ARGS.cache) if ARGS.cache else RegexChecker()


def get_inquiry():
    if ARGS.checker == 'rules':
        return Inquiry(
            subject={'name': 'Nick', 'stars': 900, 'status': 'registered'},
            resource={'method': ['post', 'get'], 'path': '/acme/users', 'id': rand_string()},
            action={'before': 'foo', 'after': rand_string()},
            context={'ip': '127.0.0.1'}
        )
    return Inquiry(action='get', subject='xo', resource='library:books:1234', context={'ip': '127.0.0.1'})


def populate_storage(store):
    global overall_policies_created
    for x in range(ARGS.policies_number):
        policy = gen_policy()
        store.add(policy)
        overall_policies_created += 1
        yield


def print_generation(generator, factor=10, line_len=LINE_LEN):
    cl, cf = 0, 0
    for _ in generator():
        if cf < factor:
            cf += 1
            continue
        print('.', end='', flush=True)
        cl += 1
        cf = 0
        if cl >= line_len:
            cl = 0
            print()
    print()


@contextlib.contextmanager
def get_storage():
    if ARGS.storage == 'mongo':
        db_name = 'vakt_db'
        collection = 'vakt_policies_benchmark'
        client = MongoClient('127.0.0.1', 27017)
        yield MongoStorage(client, db_name, collection=collection)
        client[db_name][collection].delete_many({})
        client.close()
    else:
        yield MemoryStorage()


if __name__ == '__main__':
    with get_storage() as st:
        print('=' * LINE_LEN)
        print('Populating %s with Policies' % st.__class__.__name__)
        print_generation(partial(populate_storage, st), int(ARGS.policies_number / 100 * 1), LINE_LEN)
        print('START BENCHMARK!')
        start = timeit.default_timer()
        checker = get_checker()
        inq = get_inquiry()
        allowed = Guard(st, checker).is_allowed(inquiry=inq)
        stop = timeit.default_timer()
        print('Number of unique Policies in DB: {:,}'.format(overall_policies_created))
        print('Among them Policies with the same regexp pattern: {:,}'.format(similar_regexp_policies_created))
        print('Checker used: %s' % checker.__class__.__name__)
        # print('Inquiry looks like: %s' % vars(inq))
        print('Decision for 1 Inquiry took: %0.4f seconds' % (stop - start))
        print('Inquiry passed the guard? %s' % allowed)
        print('=' * LINE_LEN)
