from app import create_app
import re

app = create_app()
app.config['TESTING'] = True
with app.test_client() as c:
    c.post('/login', data={'username': 'admin', 'password': 'admin123'})
    r = c.get('/')
    html = r.data.decode('utf-8')
    print('Has chatFab:', 'chatFab' in html)
    print('Has chatPanel:', 'chatPanel' in html)
    print('Has chatSendBtn:', 'chatSendBtn' in html)
    print('Has AI Institute Assistant:', 'AI Institute Assistant' in html)

    # Check CSS link
    css_link = re.search(r'href="([^"]*styles\.css[^"]*)"', html)
    if css_link:
        print('CSS link:', css_link.group(1))

    # Check the CSS content
    css_match = re.search(r'\.chat-fab\s*\{', html)
    print('Chat CSS inline:', 'inline chat styles found' if css_match else 'NOT INLINE - using external CSS')

    # Check if JS is rendered
    js_match = re.search(r'toggleChat', html)
    print('JS toggleChat:', 'found' if js_match else 'missing')
    js_match = re.search(r'sendChatMessage', html)
    print('JS sendChatMessage:', 'found' if js_match else 'missing')
