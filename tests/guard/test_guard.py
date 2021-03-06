import pytest

from vakt.checker import RegexChecker, RulesChecker
from vakt.storage.memory import MemoryStorage
from vakt.rules.net import CIDR
from vakt.rules.inquiry import SubjectEqual
from vakt.effects import DENY_ACCESS, ALLOW_ACCESS
from vakt.policy import Policy
from vakt.guard import Guard, Inquiry
from vakt.rules.operator import Eq
from vakt.rules.string import RegexMatch


# Create all required test policies
st = MemoryStorage()
policies = [
    Policy(
        uid='1',
        description="""
        Max, Nina, Ben, Henry are allowed to create, delete, get the resources
        only if the client IP matches and the inquiry states that any of them is the resource owner
        """,
        effect=ALLOW_ACCESS,
        subjects=('Max', 'Nina', '<Ben|Henry>'),
        resources=('myrn:example.com:resource:123', 'myrn:example.com:resource:345', 'myrn:something:foo:<.+>'),
        actions=('<create|delete>', 'get'),
        context={
            'ip': CIDR('127.0.0.1/32'),
            'owner': SubjectEqual(),
        },
    ),
    Policy(
        uid='2',
        description='Allows Max to update any resource',
        effect=ALLOW_ACCESS,
        subjects=['Max'],
        actions=['update'],
        resources=['<.*>'],
    ),
    Policy(
        uid='3',
        description='Max is not allowed to print any resource',
        effect=DENY_ACCESS,
        subjects=['Max'],
        actions=['print'],
        resources=['<.*>'],
    ),
    Policy(
        uid='4'
    ),
    Policy(
        uid='5',
        description='Allows Nina to update any resources that have only digits',
        effect=ALLOW_ACCESS,
        subjects=['Nina'],
        actions=['update'],
        resources=[r'<[\d]+>'],
    ),
    Policy(
        uid='6',
        description='Allows Nina to update any resources that have only digits. Defined by rules',
        effect=ALLOW_ACCESS,
        subjects=[Eq('Nina')],
        actions=[Eq('update'), Eq('read')],
        resources=[{'id': RegexMatch(r'\d+'), 'magazine': RegexMatch(r'[\d\w]+')}],
    ),
]
for p in policies:
    st.add(p)


@pytest.mark.parametrize('desc, inquiry, should_be_allowed, checker', [
    (
        'Empty inquiry carries no information, so nothing is allowed, even empty Policy #4',
        Inquiry(),
        False,
        RegexChecker(),
    ),
    (
        'Max is allowed to update anything',
        Inquiry(
            subject='Max',
            resource='myrn:example.com:resource:123',
            action='update'
        ),
        True,
        RegexChecker(),
    ),
    (
        'Max is allowed to update anything, even empty one',
        Inquiry(
            subject='Max',
            resource='',
            action='update'
        ),
        True,
        RegexChecker(),
    ),
    (
        'Max, but not max is allowed to update anything (case-sensitive comparison)',
        Inquiry(
            subject='max',
            resource='myrn:example.com:resource:123',
            action='update'
        ),
        False,
        RegexChecker(),
    ),
    (
        'Max is not allowed to print anything',
        Inquiry(
            subject='Max',
            resource='myrn:example.com:resource:123',
            action='print',
        ),
        False,
        RegexChecker(),
    ),
    (
        'Max is not allowed to print anything, even if no resource is given',
        Inquiry(
            subject='Max',
            action='print'
        ),
        False,
        RegexChecker(),
    ),
    (
        'Max is not allowed to print anything, even an empty resource',
        Inquiry(
            subject='Max',
            action='print',
            resource=''
        ),
        False,
        RegexChecker(),
    ),
    (
        'Policy #1 matches and has allow-effect',
        Inquiry(
            subject='Nina',
            action='delete',
            resource='myrn:example.com:resource:123',
            context={
                'owner': 'Nina',
                'ip': '127.0.0.1'
            }
        ),
        True,
        RegexChecker(),
    ),
    (
        'Policy #1 matches - Henry is listed in the allowed subjects regexp',
        Inquiry(
            subject='Henry',
            action='get',
            resource='myrn:example.com:resource:123',
            context={
                'owner': 'Henry',
                'ip': '127.0.0.1'
            }
        ),
        True,
        RegexChecker(),
    ),
    (
        'Policy #1 does not match - Henry is listed in the allowed subjects regexp. But usage of inappropriate checker',
        Inquiry(
            subject='Henry',
            action='get',
            resource='myrn:example.com:resource:123',
            context={
                'owner': 'Henry',
                'ip': '127.0.0.1'
            }
        ),
        False,
        RulesChecker(),
    ),
    (
        'Policy #1 does not match - one of the contexts was not found (misspelled)',
        Inquiry(
            subject='Nina',
            action='delete',
            resource='myrn:example.com:resource:123',
            context={
                'owner': 'Nina',
                'IP': '127.0.0.1'
            }
        ),
        False,
        RegexChecker(),
    ),
    (
        'Policy #1 does not match - one of the contexts is missing',
        Inquiry(
            subject='Nina',
            action='delete',
            resource='myrn:example.com:resource:123',
            context={
                'ip': '127.0.0.1'
            }
        ),
        False,
        RegexChecker(),
    ),
    (
        'Policy #1 does not match - context says that owner is Ben, not Nina',
        Inquiry(
            subject='Nina',
            action='delete',
            resource='myrn:example.com:resource:123',
            context={
                'owner': 'Ben',
                'ip': '127.0.0.1'
            }
        ),
        False,
        RegexChecker(),
    ),
    (
        'Policy #1 does not match - context says IP is not in the allowed range',
        Inquiry(
            subject='Nina',
            action='delete',
            resource='myrn:example.com:resource:123',
            context={
                'owner': 'Nina',
                'ip': '0.0.0.0'
            }
        ),
        False,
        RegexChecker(),
    ),
    (
        'Policy #5 does not match - action is update, but subjects does not match',
        Inquiry(
            subject='Sarah',
            action='update',
            resource='88',
        ),
        False,
        RegexChecker(),
    ),
    (
        'Policy #5 does not match - action is update, subject is Nina, but resource-name is not digits',
        Inquiry(
            subject='Nina',
            action='update',
            resource='abcd',
        ),
        False,
        RegexChecker(),
    ),
    (
        'Policy #6 does not match - Inquiry has wrong format for resource',
        Inquiry(
            subject='Nina',
            action='update',
            resource='abcd',
        ),
        False,
        RulesChecker(),
    ),
    (
        'Policy #6 does not match - Inquiry has string ID for resource',
        Inquiry(
            subject='Nina',
            action='read',
            resource={'id': 'abcd'},
        ),
        False,
        RulesChecker(),
    ),
    (
        'Policy #6 should match',
        Inquiry(
            subject='Nina',
            action='read',
            resource={'id': '00678', 'magazine': 'Playboy1'},
        ),
        True,
        RulesChecker(),
    ),
    (
        'Policy #6 should not match - usage of inappropriate checker',
        Inquiry(
            subject='Nina',
            action='read',
            resource={'id': '00678', 'magazine': 'Playboy1'},
        ),
        False,
        RegexChecker(),
    ),
])
def test_is_allowed(desc, inquiry, should_be_allowed, checker):
    g = Guard(st, checker)
    assert should_be_allowed == g.is_allowed(inquiry)


def test_is_allowed_for_none_policies():
    g = Guard(MemoryStorage(), RegexChecker())
    assert not g.is_allowed(Inquiry(subject='foo', action='bar', resource='baz'))


def test_not_allowed_when_similar_policies_have_at_least_one_deny_access():
    st = MemoryStorage()
    policies = (
        Policy(
            uid='1',
            effect=ALLOW_ACCESS,
            subjects=['foo'],
            actions=['bar'],
            resources=['baz'],
        ),
        Policy(
            uid='2',
            effect=DENY_ACCESS,
            subjects=['foo'],
            actions=['bar'],
            resources=['baz'],
        ),
    )
    for p in policies:
        st.add(p)
    g = Guard(st, RegexChecker())
    assert not g.is_allowed(Inquiry(subject='foo', action='bar', resource='baz'))


def test_guard_if_unexpected_exception_raised():
    # for testing unexpected exception
    class BadMemoryStorage(MemoryStorage):
        def find_for_inquiry(self, inquiry=None, checker=None):
            raise Exception('This is test class that raises errors')
    g = Guard(BadMemoryStorage(), RegexChecker())
    assert not g.is_allowed(Inquiry(subject='foo', action='bar', resource='baz'))
