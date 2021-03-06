[![Vakt logo](logo.png)](logo.png)

Attribute-based access control (ABAC) SDK for Python.

[![Build Status](https://travis-ci.org/kolotaev/vakt.svg?branch=master)](https://travis-ci.org/kolotaev/vakt)
[![codecov.io](https://codecov.io/github/kolotaev/vakt/coverage.svg?branch=master)](https://codecov.io/github/kolotaev/vakt?branch=master)
[![PyPI version](https://badge.fury.io/py/vakt.svg)](https://badge.fury.io/py/vakt)
[![Apache 2.0 licensed](https://img.shields.io/badge/License-Apache%202.0-yellow.svg)](https://raw.githubusercontent.com/kolotaev/vakt/master/LICENSE)

------

## Documentation

- [Description](#description)
- [Concepts](#concepts)
- [Install](#install)
- [Usage](#usage)
- [Components](#components)
	- [Policy](#policy)
	- [Inquiry](#inquiry)
	- [Rules](#rules)
	    - [Comparison-related](#comparison-related)
	    - [Logic-related](#logic-related)
	    - [List-related](#list-related)
	    - [Network-related](#network-related)
	    - [String-related](#string-related)
	    - [Inquiry-related](#inquiry-related)
	- [Checker](#checker)
	- [Guard](#guard)
	- [Storage](#storage)
        - [Memory](#memory)
        - [MongoDB](#mongodb)
    - [Migration](#migration)
- [JSON](#json)
- [Logging](#logging)
- [Examples](./examples)
- [Acknowledgements](#acknowledgements)
- [Benchmark](#benchmark)
- [Development](#development)
- [License](#license)


### Description

Vakt is an attribute-based access control ([ABAC](https://en.wikipedia.org/wiki/Attribute-based_access_control))
toolkit that is based on policies, also sometimes referred as PBAC.
ABAC stands aside of RBAC and ACL models, giving you
a fine-grained control on definition of the rules that restrict an access to resources and is generally considered a
"next generation" authorization model.
In its form Vakt resembles [IAM Policies](https://github.com/awsdocs/iam-user-guide/blob/master/doc_source/access_policies.md), but
has a way nicer attribute managing.

See [concepts](#concepts) section for more details.

*[Back to top](#documentation)*


### Concepts

Given you have some set of resources, you can define a number of policies that will describe access to them
answering the following questions:

1. *What resources (resource) are being requested?*
1. *Who is requesting the resource?*
1. *What actions (action) are requested to be done on the asked resources?*
1. *What are the rules that should be satisfied in the context of the request itself?*
1. *What is resulting effect of the answer on the above questions?*


The overall diagram of `vakt` workflow is:

[![Vakt diagram](diagram.svg)](diagram.svg)


Vakt allows you to gain:

* Policy Based Access Control _(vakt is based on Policies that describe access rules, strategies to your resources)_
* Fine-Grained Authorization _(vakt Policies give you fine-grained control over resource's, subject's, action's and context's attributes)_
* Dynamic Authorization Management _(you can add Policies and change their attributes)_
* Externalized Authorization Management _(you can build own external AuthZ server with vakt, see examples)_

*[Back to top](#documentation)*


### Install

Vakt runs on Python >= 3.4.  
PyPy implementation is supported as well.

For in-memory storage:
```bash
pip install vakt
```

For MongoDB storage:
```bash
pip install vakt[mongo]
```

*[Back to top](#documentation)*


### Usage

A quick dive-in:

```python
import uuid

import vakt
from vakt.rules import Eq, Any, StartsWith, And, Greater, Less

policy = vakt.Policy(
    str(uuid.uuid4()),
    actions=[Eq('fork'), Eq('clone')],
    resources=[StartsWith('repos/Google', ci=True)],
    subjects=[{'name': Any(), 'stars': And(Greater(50), Less(999))}],
    effect=vakt.ALLOW_ACCESS,
    context={'referer': 'https://github.com'},
    description="""
    Allow to fork or clone any Google repository for
    users that have > 50 and < 999 stars and came from Github
    """
)
storage = vakt.MemoryStorage()
storage.add(policy)
guard = vakt.Guard(storage, vakt.RulesChecker())

inq = vakt.Inquiry(action='fork',
                   resource='repos/google/tensorflow',
                   subject={'name': 'larry', 'stars': 80},
                   context={'referer': 'https://github.com'})

assert guard.is_allowed(inq)
```

For more examples see [here](./examples).

*[Back to top](#documentation)*

### Components

#### Policy
Policy is a main object for defining rules for accessing resources.
The main parts reflect questions described in [Concepts](#concepts) section:

* resources - a list of resources. Answers: what is asked?
* subjects  - a list of subjects. Answers: who asks access to resources?
* actions - a list of actions. Answers: what actions are asked to be performed on resources?
* context - rules that should be satisfied by the given inquiry's context.
* effect - If policy matches all the above conditions, what effect does it imply?
Can be either `vakt.ALLOW_ACCESS` or `vakt.DENY_ACCESS`

All `resources`, `subjects` and `actions` are described with 
a list containing strings, regexes, [Rules](#rules) or dictionaries of strings (attributes) to [Rules](#rules). 
Each element in list acts as logical OR. Each key in a dictionary of Rules acts as logical AND.   
`context` can be described only with a dictionary of [Rules](#rules).

Depending on a way `resources`, `subjects`, `actions` are described, Policy can have either 
String-based or Rule-based type. Can be inspected by `policy.type`. 
This enforces the use of a concrete Checker implementation. See [Checker](#checker) for more.

```python
from vakt import Policy, ALLOW_ACCESS
from vakt.rules import CIDR, Any, Eq, NotEq, In
    
# Rule-based policy (defined with Rules and dictionaries of Rules)
Policy(
    1,
    description="""
    Allow access to administration interface subcategories: 'panel', 'switch' if user is not 
    a developer and came from local IP address.
    """,
    actions=[Any()],
    resources=[{'category': Eq('administration'), 'sub': In(['panel', 'switch'])}],
    subjects=[{'name': Any(), 'role': NotEq('developer')}],
    effect=ALLOW_ACCESS,
    context={'ip': CIDR('127.0.0.1/32')}
)

# String-based policy (defined with regular expressions)
Policy(
    2,
    description="""
    Allow all readers of the book library whose surnames start with M get and read any book or magazine,
    but only when they connect from local library's computer
    """,
    effect=ALLOW_ACCESS,
    subjects=['<[\w]+ M[\w]+>'],
    resources=('library:books:<.+>', 'office:magazines:<.+>'),
    actions=['<read|get>'],
    context={'ip': CIDR('192.168.2.0/24')}
)
```

Basically you want to create some set of Policies that encompass access rules for your domain and store them for
making future decisions by the [Guard](#guard) component.

```python
st = MemoryStorage()
for p in policies:
    st.add(p)
```

*[Back to top](#documentation)*


#### Inquiry
Inquiry is an object that serves as a mediator between Vakt and outer world request for resource access. All you need
to do is take any kind of incoming request (REST request, SOAP, etc.) and build an `Inquiry` out of it in order to
feed it to Vakt. There are no concrete builders for Inquiry from various request types, since it's a very meticulous
process and you have hands on control for doing it by yourself. Let's see an example:

```python
from vakt import Inquiry
from flask import request, session

...

# if policies are defined on some subject's and resource's attributes with dictionaries of Rules:
inquiry2 = Inquiry(subject={'login': request.form['username'], 'role': request.form['user_role']},
                   action=request.form['action'],
                   resource={'book': session.get('book'), 'chapter': request.form['chapter']},
                   context={'ip': request.remote_addr})
                   
# if policies are defined with strings or regular expressions:
inquiry = Inquiry(subject=request.form['username'],
                  action=request.form['action'],
                  resource=request.form['page'],
                  context={'ip': request.remote_addr})
```

Here we are taking form params from Flask request and additional request information. Then we transform them
to Inquiry. That's it.

Inquiry has several constructor arguments:

* resource - any | dictionary of str -> any. What resource is being asked to be accessed?
* action - any | dictionary str -> any. What is being asked to be done on the resource?
* subject - any | dictionary str -> any. Who asks for it?
* context - dictionary str -> any. What is the context of the request?

If you were observant enough you might have noticed that Inquiry resembles Policy, where Policy describes multiple
variants of resource access from the owner side and Inquiry describes an concrete access scenario from consumer side.

*[Back to top](#documentation)*


#### Rules
Rules allow you to describe conditions directly on `action`, `subject`, `resource` and `context` 
or on their attributes.
If at least one Rule in the Rule-set is not satisfied Inquiry is rejected by given Policy.

Attaching a Rule-set to a Policy is simple. Here are some examples:

```python
from vakt import Policy, rules

Policy(
    ...,
    subjects=[{'name': rules.Eq('.KIMZihH0gsrc')}],
),

Policy(
    ...,
    actions=[rules.Eq('get'), rules.Eq('list'), rules.Eq('read')],
),

Policy(
    ...,
    context={
        'secret': rules.string.Equal('.KIMZihH0gsrc'),
        'ip': rules.net.CIDR('192.168.0.15/24')
    },
)
```

There are a number of different Rule types, see below.

If the existing Rules are not enough for you, feel free to define your [own](./examples/extending.py).

##### Comparison-related

| Rule          | Example in Policy  |  Example in Inquiry  | Notes |
| ------------- |-------------|-------------|-------------|
| Eq      | `'age': Eq(40)` | `'age': 40`| |
| NotEq      | `'age': NotEq(40)` | `'age': 40`| |
| Greater      | `'height': Greater(6,2)` | `'height': 5.8`| |
| Less      | `'height': Less(6,2)` | `'height': 5.8`| |
| GreaterOrEqual      | `'stars': GreaterOrEqual(300)` | `'stars': 77`| |
| LessOrEqual      | `'stars': LessOrEqual(300)` | `'stars': 300`| |

##### Logic-related

| Rule          | Example in Policy  |  Example in Inquiry  | Notes |
| ------------- |-------------|-------------|-------------|
| Truthy    | `'admin': Truthy()` | `'admin': user.is_admin()`| Evaluates on Inquiry creation |
| Falsy     | `'admin': Falsy()` | `'admin': lambda x: x.is_admin()`| Evaluates on Inquiry creation |
| Not   | `'age': Not(Greater(90))` | `'age': 40` | |
| And   | `'stars': And(Greater(50), Less(89))` | `'stars': 78` | Also, attributes in dictionary of Rules act as AND logic |
| Or    | `'stars': Or(Greater(50), Less(120), Eq(8888))` | `'stars': 78` | Also, rules in a list of, say, `actions` act as OR logic |
| Any      | `actions=[Any()]` | `action='get'`, `action='foo'` | Placeholder that fits any value |
| Neither      | `subjects=[Neither()]` | `subject='Max'`,  `subject='Joe'` | Not very useful, left only as a counterpart of Any |

##### List-related
| Rule          | Example in Policy  |  Example in Inquiry  | Notes |
| ------------- |-------------|-------------|-------------|
| In    | `'method': In('get', 'post')` | `'method': 'get'`| |
| NotIn    | `'method': NotIn('get', 'post')` | `'method': 'get'`| |
| AllIn    | `'name': AllIn('Max', 'Joe')` | `'name': ['Max', 'Joe']`| |
| AllNotIn    | `'name': AllNotIn('Max', 'Joe')` | `'name': ['Max', 'Joe']`| |
| AnyIn    | `'height': AnyIn(5.9, 7.5, 4.9)` | `'height': [7.55]`| |
| AnyNotIn    | `'height': AnyNotIn(5.9, 7.5, 4.9)` | `'height': [7.55]`| |

##### Network-related

| Rule          | Example in Policy  |  Example in Inquiry  | Notes |
| ------------- |-------------|-------------|-------------|
| CIDR    | `'ip': CIDR('192.168.2.0/24')` | `'ip': 192.168.2.4`| |

##### String-related
| Rule          | Example in Policy  |  Example in Inquiry  | Notes |
| ------------- |-------------|-------------|-------------|
| Equal    | `'name': Equal('max', ci=True)` | `'name': 'Max'`| Aliased as `StrEqual`. Use instead of `Eq` it you want string-type check and case-insensitivity |
| PairsEqual    | `'names': PairsEqual()` | `'names': ['Bob', 'Bob']`| Aliased as `StrPairsEqual` |
| RegexMatch    | `'file': RegexMatch(r'\.rb$')` | `'file': 'test.rb'`| |
| StartsWith    | `'file': StartsWith('logs-')` | `'file': 'logs-data-101967.log'`| Supports case-insensitivity |
| EndsWith    | `'file': EndsWith('.log')` | `'file': 'logs-data-101967.log'`| Supports case-insensitivity |
| Contains    | `'file': Contains('sun')` | `'file': 'observations-sunny-days.csv'`| Supports case-insensitivity |

##### Inquiry-related

Inquiry-related rules are not usable since v1.2, so you very likely won't need them.
Partially they served as attributes workaround for inquiry elements when placed in `context`.

| Rule          | Example in Policy  |  Example in Inquiry  | Notes |
| ------------- |-------------|-------------|-------------|
| SubjectEqual  | `'data': SubjectEqual()` | `Inquiry(subject='Max')`| Works only for strings |
| ActionEqual  | `'data': ActionEqual()` | `Inquiry(action='get')`| Works only for strings |
| ResourceIn  | `'data': ResourceIn()` | `Inquiry(resource='/books/')`| Works only for strings |


*[Back to top](#documentation)*


#### Checker
Checker allows you to check whether Policy matches Inquiry by concrete field (`subject`, `action`, etc.). It's used
internally by [Guard](#guard), but you should be aware of Checker types:

* RulesChecker - universal type that is used to check match of Policies defined with Rules or dictionaries of Rules
(Rule-based Policy type). It gives you the highest flexibility.
Most of the time you will use this type of Polices and thus this type of a Checker.
Besides, it's much more performant than RegexChecker. See [benchmark](#benchmark) for more details.

```python
from vakt import RulesChecker

ch = RulesChecker()
# etc.
```

* RegexChecker - checks match by regex test for policies defined with strings and regexps (String-based Policy type).
This means that all you Policies
can be defined in regex syntax (but if no regex defined in Policy falls back to simple string equality test) - it
gives you better flexibility compared to simple strings, but carries a burden of relatively slow performance.
You can configure a LRU cache size to adjust performance to your needs:

```python
from vakt import RegexChecker

ch = RegexChecker(2048)
ch2 = RegexChecker(512)
# etc.
```
See [benchmark](#benchmark) for more details.

Syntax for description of Policy fields is:
```
 '<foo.*>'
 'foo<[abc]{2}>bar'
 'foo<\w+>'
 'foo'
```
Where `<>` are delimiters of a regular expression boundaries part. Custom Policy can redefine them by overriding
`start_tag` and `end_tag` properties. Generally you always want to use the first variant: `<foo.*>`.

* StringExactChecker - the most quick checker:
```
Checker that uses exact string equality. Case-sensitive.
E.g. 'sun' in 'sunny' - False
     'sun' in 'sun' - True
```
* StringFuzzyChecker - quick checker with some extent of flexibility:
```
Checker that uses fuzzy substring equality. Case-sensitive.
E.g. 'sun' in 'sunny' - True
     'sun' in 'sun' - True
```

Note, that some [Storage](#storage) handlers can already check if Policy fits Inquiry in
`find_for_inquiry()` method by performing specific to that storage queries - Storage can (and generally should)
decide on the type of actions based on the checker class passed to [Guard](#guard) constructor
(or to `find_for_inquiry()` directly).

Regardless of the results returned by a Storage the Checker is always the last row of control
before Vakt makes a decision.

*[Back to top](#documentation)*


#### Guard
Guard component is a main entry point for Vakt to make a decision. It has one method `is_allowed` that passed an
[Inquiry](#inquiry) gives you a boolean answer: is that Inquiry allowed or not?

Guard is constructed with [Storage](#storage) and [Checker](#checker).

__Policies that have String-based type won't match if RulesChecker is used and vise-versa.__

```python
st = MemoryStorage()
# And persist all our Policies so that to start serving our library.
for p in policies:
    st.add(p)

guard = Guard(st, RulesChecker())

if guard.is_allowed(inquiry):
    return "You've been logged-in", 200
else:
    return "Go away, you violator!", 401
```

*[Back to top](#documentation)*


#### Storage
Storage is a component that gives an interface for manipulating [Policies](#policy) persistence in various places.

It provides the following methods:
```python
add(policy)                 # Store a Policy
get(uid)                    # Retrieve a Policy by its ID
get_all(limit, offset)      # Retrieve all stored Policies (with pagination)
update(policy)              # Store an updated Policy
delete(uid)                 # Delete Policy from storage by its ID
find_for_inquiry(inquiry)   # Retrieve Policies that match the given Inquiry
```

Storage may have various backend implementations (RDBMS, NoSQL databases, etc.). Vakt ships some Storage implementations
out of the box. See below.

##### Memory
Implementation that stores Policies in memory. It's not backed by any file or something, so every restart of your
application will swipe out everything that was stored. Useful for testing.

```python
from vakt import MemoryStorage

storage = MemoryStorage()
```

##### MongoDB
MongoDB is chosen as the most popular and widespread NO-SQL database.


```python
from pymongo import MongoClient
from vakt.storage.mongo import MongoStorage

client = MongoClient('localhost', 27017)
storage = MongoStorage(client, 'database-name', collection='optional-collection-name')
```

Default collection name is 'vakt_policies'.

Actions are the same as for any Storage that conforms interface of `vakt.storage.abc.Storage` base class.

Beware that currently MongoStorage supports indexed `find_for_inquiry()` only for StringExact and StringFuzzy checkers.
RegexChecker (see [this issue](https://jira.mongodb.org/browse/SERVER-11947)) and RulesChecker simply
return all the Policies from the database.

*[Back to top](#documentation)*


#### Migration

`vakt.migration` is a set of components that are useful from the perspective of the [Storage](#storage).
It's recommended to favor it over manual actions on DB schema/data
since it's aware of Vakt requirements to Policies data. But it's not mandatory, anyway.
However it's up to a particular Storage to decide whether it needs migrations or not.
It consists of 3 components:
* `Migration`
* `MigrationSet`
* `Migrator`

`Migration` allows you to describe data modifications between versions.
Each storage can have a number of `Migration` classes to address different releases with the order of the migration
specified in `order` property.
Should be located inside particular storage module and implement `vakt.storage.migration.Migration`.
Migration has 2 main methods (as you might guess) and 1 property:
- `up` - runs db "schema" upwards
- `down` - runs db "schema" downwards (rolls back the actions of `up`)
- `order` - tells the number of the current migration in a row

`MigrationSet` is a component that represents a collection of Migrations for a Storage.
You should define your own migration-set. It should be located inside particular storage module and implement
`vakt.storage.migration.MigrationSet`. It has 3 methods that lest unimplemented:
- `migrations` - should return all initialized Migration objects
- `save_applied_number` - saves a number of a lst applied up migration in the Storage for later reference
- `last_applied` - returns a number of a lst applied up migration from the Storage

`Migrator` is an executor of a migrations. It can execute all migrations up or down, or execute a particular migration
if `number` argument is provided.

Example usage:

```python
from pymongo import MongoClient
from vakt.storage.mongo import MongoStorage, MongoMigrationSet
from vakt.storage.migration import Migrator

client = MongoClient('localhost', 27017)
storage = MongoStorage(client, 'database-name', collection='optional-collection-name')

migrator = Migrator(MongoMigrationSet(storage))
migrator.up()
...
migrator.down()
...
migrator.up(number=2)
...
migrator.down(number=2)
```

*[Back to top](#documentation)*


### JSON

All Policies, Inquiries and Rules can be JSON-serialized and deserialized.

For example, for a Policy all you need is just run:
```python
from vakt.policy import Policy

policy = Policy('1')

json_policy = policy.to_json()
print(json_policy)
# {"actions": [], "description": null, "effect": "deny", "uid": "1",
# "resources": [], "context": {}, "subjects": []}

policy = Policy.from_json(json_policy)
print(policy)
# <vakt.policy.Policy object at 0x1023ca198>
```

The same goes for Rules, Inquiries.
All custom classes derived from them support this functionality as well.
If you do not derive from Vakt's classes, but want this option, you can mix-in `vakt.util.JsonSerializer` class.

```python
from vakt.util import JsonSerializer

class CustomInquiry(JsonSerializer):
    pass
```

*[Back to top](#documentation)*


### Logging

Vakt follows a common logging pattern for libraries:

Its corresponding modules log all the events that happen but the log messages by default are handled by `NullHandler`.
It's up to the outer code/application to provide desired log handlers, filters, levels, etc.

For example:

```python
import logging

root = logging.getLogger()
root.setLevel(logging.INFO)
root.addHandler(logging.StreamHandler())

... # here go all the Vakt calls.
```

Vakt logs can be comprehended in 2 basic levels:
1. *Error/Exception* - informs about exceptions and errors during Vakt work.
2. *Info* - informs about incoming inquires and their resolution.

*[Back to top](#documentation)*


### Acknowledgements

Initial code ideas of Vakt are based on
[Amazon IAM Policies](https://github.com/awsdocs/iam-user-guide/blob/master/doc_source/access_policies.md) and
[Ladon](https://github.com/ory/ladon) Policies SDK as its reference implementation.

*[Back to top](#documentation)*


### Benchmark

You can see how much time it takes for a single Inquiry to be processed given we have a number of unique Policies in a
Storage. 
For [MemoryStorage](#memory) it measures the runtime of a decision-making process for all 
the existing Policies when [Guard's](#guard) code iterates the whole list of Policies to decide if 
Inquiry is allowed or not. In case of other Storages the mileage
may vary since they may return a smaller subset of Policies that fit the given Inquiry. 
Don't forget that most external Storages add some time penalty to perform I/O operations.
The runtime also depends on a Policy-type used (and thus checker): RulesChecker performs much better than RegexChecker.

Example:

```bash
python3 benchmark.py --checker regex --storage memory -n 1000
```

Output is:
> Populating MemoryStorage with Policies<br />
> ......................<br />
> START BENCHMARK!<br />
> Number of unique Policies in DB: 1,000<br />
> Among them Policies with the same regexp pattern: 0<br />
> Checker used: RegexChecker<br />
> Decision for 1 Inquiry took: 0.4451 seconds<br />
> Inquiry passed the guard? False<br />

Script usage:
```
usage: benchmark.py [-h] [-n [POLICIES_NUMBER]] [-d {mongo,memory}]
                    [-c {regex,rules,exact,fuzzy}] [--regexp] [--same SAME]
                    [--cache CACHE]

Run vakt benchmark.

optional arguments:
  -h, --help            show this help message and exit
  -n [POLICIES_NUMBER], --number [POLICIES_NUMBER]
                        number of policies to create in DB (default: 100000)
  -d {mongo,memory}, --storage {mongo,memory}
                        type of storage (default: memory)
  -c {regex,rules,exact,fuzzy}, --checker {regex,rules,exact,fuzzy}
                        type of checker (default: regex)

regex policy related:
  --regexp              should Policies be defined without Regex syntax?
                        (default: True)
  --same SAME           number of similar regexps in Policy
  --cache CACHE         number of LRU-cache for RegexChecker (default:
                        RegexChecker's default cache-size)
```

*[Back to top](#documentation)*


### Development

To hack Vakt locally run:

```bash
$ ...                              # activate virtual environment w/ preferred method (optional)
$ pip install -e .[dev,mongo]      # to install all dependencies
$ pytest -m "not integration"      # to run non-integration tests with coverage report
$ pytest --cov=vakt tests/         # to get coverage report
$ pylint vakt                      # to check code quality with PyLint
```

To run only integration tests (for Storage adapters other than `MemoryStorage`):

```bash
$ docker run --rm -d -p 27017:27017 mongo
$ pytest -m integration
```

Optionally you can use `make` to perform development tasks.

*[Back to top](#documentation)*


### License

The source code is licensed under Apache License Version 2.0

*[Back to top](#documentation)*
