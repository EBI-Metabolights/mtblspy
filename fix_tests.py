import re
from pathlib import Path
p = Path('tests/test_cli.py')
text = p.read_text()

# fix jwt_token=None missing in assert_called_once_with
text = re.sub(r'mock_client_cls\.assert_called_once_with\(([^)]*base_url=[^,)]*)\)', r'mock_client_cls.assert_called_once_with(\1, jwt_token=None)', text)

# fix the other test_auth_login_jwt_ignores_username_password
# It has client.login_with_jwt.assert_called_once_with(jwt_token)
text = re.sub(r'client\.login_with_jwt\.assert_called_once_with\(\s*jwt_token\s*\)', r'client.login_with_jwt.assert_called_once_with(jwt_token, fetch_api_token=True)', text)

p.write_text(text)
