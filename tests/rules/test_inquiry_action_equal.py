import pytest

from vakt.rules.inquiry import ActionEqual, ActionEqualRule
from vakt.guard import Inquiry


@pytest.mark.parametrize('what, action, result', [
    ('foo', 'foo', True),
    ('foo', 'bar', False),
    ('тест', 'нет', False),
    ('тест', 'тест', True),
    (1, '1', False),
    ('1', 1, False),
    ('', '', True),
])
def test_action_equal_satisfied(what, action, result):
    i = Inquiry(action=action, resource=None, subject=None)
    c = ActionEqual()
    assert result == c.satisfied(what, i)
    # test after (de)serialization
    jsn = ActionEqual().to_json()
    c1 = ActionEqual.from_json(jsn)
    assert result == c1.satisfied(what, i)
    # test deprecated class
    with pytest.deprecated_call():
        i = Inquiry(action=action, resource=None, subject=None)
        c = ActionEqualRule()
        assert result == c.satisfied(what, i)
        assert result == ActionEqualRule.from_json(c.to_json()).satisfied(what, i)
