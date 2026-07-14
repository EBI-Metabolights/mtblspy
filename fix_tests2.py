import re
from pathlib import Path
p = Path('tests/test_cli.py')
text = p.read_text()

# fix jwt_token=None in SubmissionClient mocks (for login and logout tests)
# these tests still use SubmissionClient directly which doesn't take jwt_token
# test names start with test_auth_login_ or test_auth_logout_
# It's easier to just find the mock_client_cls.assert_called_once_with(base_url=..., jwt_token=None) and replace it
# specifically in the functions for login and logout.
# actually, since create_submission_client was only used for submissions, any mock_client_cls that is SubmissionClient
# should not have jwt_token=None.
# Let's revert the jwt_token=None in lines that are inside test_auth_*
def fix_auth_tests(match):
    body = match.group(0)
    body = body.replace(", jwt_token=None", "")
    body = body.replace("client.login_with_jwt.assert_called_once_with(\"jwt-token\")", "client.login_with_jwt.assert_called_once_with(\"jwt-token\", fetch_api_token=True)")
    return body

text = re.sub(r'def test_auth_.*?(?=def test_|$)', fix_auth_tests, text, flags=re.DOTALL)

p.write_text(text)
