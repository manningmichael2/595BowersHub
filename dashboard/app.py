"""595BowersHub Dashboard — serves the HTML + proxies API calls to avoid CORS."""
from flask import Flask, send_from_directory, jsonify, request
import requests
import subprocess
import os

app = Flask(__name__, static_folder='.', static_url_path='')

# Database connection settings (from env vars, never hardcoded)
DB_HOST = os.environ.get('DB_HOST', 'postgres')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'finance')
DB_USER = os.environ.get('DB_USER', 'michael')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

# Service base host. The dashboard runs on the host network and reaches the
# other services over the Tailscale address, so this is a single env-overridable
# host (default keeps the current address) instead of the IP hardcoded four times
# — a host change is now one var, not a code edit across every service URL.
BOWERSHUB_HOST = os.environ.get('BOWERSHUB_HOST', '100.106.180.101')
N8N = f'http://{BOWERSHUB_HOST}:5678'
FILEWRITER = f'http://{BOWERSHUB_HOST}:5001'
NETDATA = f'http://{BOWERSHUB_HOST}:19999'
AUDIOBOOKSHELF = f'http://{BOWERSHUB_HOST}:13378'
AUDIOBOOKSHELF_TOKEN = os.environ.get('AUDIOBOOKSHELF_TOKEN', '')

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/weather')
def weather():
    """Get weather via wttr.in (no webhook needed)."""
    try:
        r = requests.get('https://wttr.in/Clawson,MI?format=j1', timeout=5)
        if r.ok:
            data = r.json()
            current = data.get('current_condition', [{}])[0]
            return jsonify({
                'ok': True,
                'temp_f': current.get('temp_F', '—'),
                'feels_like_f': current.get('FeelsLikeF', '—'),
                'humidity': current.get('humidity', '—'),
                'wind_mph': current.get('windspeedMiles', '—'),
                'condition': current.get('weatherDesc', [{}])[0].get('value', '—'),
                'icon': _weather_icon(current.get('weatherCode', ''))
            })
    except:
        pass
    return jsonify({'ok': False})

@app.route('/api/proxy/n8n', methods=['POST'])
def proxy_n8n():
    """Proxy requests to n8n webhooks."""
    body = request.get_json(force=True)
    path = body.get('path', '')
    payload = body.get('payload', {})
    method = body.get('method', 'POST').upper()
    try:
        if method == 'GET':
            r = requests.get(f'{N8N}/webhook/{path}', timeout=15)
        else:
            r = requests.post(f'{N8N}/webhook/{path}', json=payload, timeout=15)
        return jsonify(r.json() if r.ok else {'error': f'HTTP {r.status_code}'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/proxy/filewriter', methods=['POST'])
def proxy_filewriter():
    """Proxy POST requests to filewriter."""
    body = request.get_json(force=True)
    endpoint = body.get('endpoint', '')
    payload = body.get('payload', {})
    try:
        r = requests.post(f'{FILEWRITER}/{endpoint}', json=payload, timeout=10)
        return jsonify(r.json() if r.ok else {'error': f'HTTP {r.status_code}'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/proxy/netdata')
def proxy_netdata():
    """Proxy GET requests to Netdata API."""
    path = request.args.get('path', '')
    try:
        r = requests.get(f'{NETDATA}/{path}', timeout=5)
        return jsonify(r.json() if r.ok else {'error': f'HTTP {r.status_code}'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/tailscale')
def tailscale():
    """Get tailscale peer status."""
    try:
        r = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            import json
            data = json.loads(r.stdout)
            peers = []
            # Self
            myself = data.get('Self', {})
            if myself:
                peers.append({'name': myself.get('HostName', '?'), 'ip': myself.get('TailscaleIPs', ['?'])[0], 'online': True, 'os': myself.get('OS', '?'), 'is_self': True})
            # Peers
            for pid, p in data.get('Peer', {}).items():
                peers.append({
                    'name': p.get('HostName', '?'),
                    'ip': p.get('TailscaleIPs', ['?'])[0],
                    'online': p.get('Online', False),
                    'os': p.get('OS', '?'),
                    'last_seen': p.get('LastSeen', ''),
                    'is_self': False
                })
            return jsonify({'ok': True, 'peers': peers})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})
    return jsonify({'ok': False, 'error': 'tailscale not available'})

@app.route('/api/anthropic-spend')
def anthropic_spend():
    """Query API usage from the n8n logger webhook."""
    days = request.args.get('days', '7')
    try:
        r = requests.get(f'{N8N}/webhook/api-usage', params={'days': days}, timeout=10)
        if r.ok:
            data = r.json()
            return jsonify(data)
    except Exception as e:
        pass
    # Fallback: query Postgres directly if webhook isn't available
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=int(DB_PORT),
            dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
        )
        cur = conn.cursor()
        cur.execute(f"""
            SELECT
                called_at::date::text AS day,
                workflow_name,
                model,
                COUNT(*) AS call_count,
                SUM(input_tokens) AS total_input,
                SUM(output_tokens) AS total_output,
                SUM(cost_usd)::numeric(10,4) AS total_cost
            FROM public.api_usage_log
            WHERE called_at > now() - interval '{int(days)} days'
            GROUP BY day, workflow_name, model
            ORDER BY day DESC, total_cost DESC
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        cur.close()
        conn.close()

        by_day = {}
        by_workflow = {}
        by_model = {}
        total_cost = 0
        total_calls = 0

        for row in rows:
            r_dict = dict(zip(cols, row))
            day = r_dict['day']
            wf = r_dict['workflow_name'] or 'unknown'
            mdl = r_dict['model'] or 'unknown'
            cost = float(r_dict['total_cost'] or 0)
            calls = int(r_dict['call_count'] or 0)

            if day not in by_day:
                by_day[day] = {'cost': 0, 'calls': 0, 'input_tokens': 0, 'output_tokens': 0}
            by_day[day]['cost'] += cost
            by_day[day]['calls'] += calls
            by_day[day]['input_tokens'] += int(r_dict['total_input'] or 0)
            by_day[day]['output_tokens'] += int(r_dict['total_output'] or 0)

            if wf not in by_workflow:
                by_workflow[wf] = {'cost': 0, 'calls': 0}
            by_workflow[wf]['cost'] += cost
            by_workflow[wf]['calls'] += calls

            if mdl not in by_model:
                by_model[mdl] = {'cost': 0, 'calls': 0}
            by_model[mdl]['cost'] += cost
            by_model[mdl]['calls'] += calls

            total_cost += cost
            total_calls += calls

        return jsonify({
            'ok': True,
            'total_cost_usd': round(total_cost, 4),
            'total_calls': total_calls,
            'by_day': by_day,
            'by_workflow': by_workflow,
            'by_model': by_model,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e), 'note': 'No usage data yet. Run migration 007 and deploy the logger workflow.'})

@app.route('/api/emails')
def recent_emails():
    """Fetch recent emails via IMAP directly."""
    try:
        from imap_tools import MailBox
        mb = MailBox('imap.gmail.com').login(
            os.environ.get('GMAIL_IMAP_USER', 'manningmichael2@gmail.com'),
            os.environ.get('GMAIL_IMAP_PASSWORD', '')
        )
        mb.folder.set('INBOX')
        msgs = list(mb.fetch(limit=5, reverse=True))
        emails = []
        for m in msgs:
            emails.append({
                'from': str(m.from_)[:40],
                'subject': (m.subject or '(no subject)')[:60],
                'date': m.date.strftime('%b %d %H:%M') if m.date else '',
            })
        mb.logout()
        return jsonify({'ok': True, 'emails': emails, 'count': len(emails)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/audiobookshelf')
def audiobookshelf():
    """Get Audiobookshelf library stats and currently listening."""
    if not AUDIOBOOKSHELF_TOKEN:
        return jsonify({'ok': False, 'error': 'AUDIOBOOKSHELF_TOKEN not set'})
    headers = {'Authorization': f'Bearer {AUDIOBOOKSHELF_TOKEN}'}
    try:
        # Get libraries
        libs = requests.get(f'{AUDIOBOOKSHELF}/api/libraries', headers=headers, timeout=5).json()
        library_id = libs.get('libraries', [{}])[0].get('id', '') if libs.get('libraries') else ''

        # Get library stats
        stats = {}
        if library_id:
            stats = requests.get(f'{AUDIOBOOKSHELF}/api/libraries/{library_id}/stats', headers=headers, timeout=5).json()

        # Get in-progress items
        progress = requests.get(f'{AUDIOBOOKSHELF}/api/me/items-in-progress', headers=headers, timeout=5).json()
        in_progress = []
        for item in (progress.get('libraryItems') or [])[:3]:
            media = item.get('media', {})
            meta = media.get('metadata', {})
            # Get progress percentage
            prog_data = item.get('userMediaProgress', {})
            pct = round((prog_data.get('progress', 0)) * 100)
            in_progress.append({
                'title': meta.get('title', '?'),
                'author': meta.get('authorName', '?'),
                'progress_pct': pct,
            })

        # Format total duration
        total_secs = stats.get('totalDuration', 0)
        total_hours = round(total_secs / 3600)

        return jsonify({
            'ok': True,
            'total_items': stats.get('totalItems', 0),
            'total_authors': stats.get('totalAuthors', 0),
            'total_hours': total_hours,
            'total_size_gb': round(stats.get('totalSize', 0) / (1024**3), 1),
            'in_progress': in_progress,
            'top_authors': [a['name'] for a in (stats.get('authorsWithCount') or [])[:3]],
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


def _weather_icon(code):
    code = str(code)
    icons = {
        '113': '☀️', '116': '⛅', '119': '☁️', '122': '☁️',
        '143': '🌫️', '176': '🌦️', '179': '🌨️', '182': '🌨️',
        '200': '⛈️', '227': '🌨️', '230': '❄️', '248': '🌫️',
        '260': '🌫️', '263': '🌦️', '266': '🌧️', '281': '🌨️',
        '284': '🌨️', '293': '🌦️', '296': '🌧️', '299': '🌧️',
        '302': '🌧️', '305': '🌧️', '308': '🌧️', '311': '🌨️',
        '314': '🌨️', '317': '🌨️', '320': '🌨️', '323': '🌨️',
        '326': '🌨️', '329': '❄️', '332': '❄️', '335': '❄️',
        '338': '❄️', '350': '🌨️', '353': '🌦️', '356': '🌧️',
        '359': '🌧️', '362': '🌨️', '365': '🌨️', '368': '🌨️',
        '371': '❄️', '374': '🌨️', '377': '🌨️', '386': '⛈️',
        '389': '⛈️', '392': '⛈️', '395': '❄️',
    }
    return icons.get(code, '🌡️')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
