"""Read-only Google OAuth/REST, configured public research and factual briefings."""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as daytime, timedelta, timezone
from email.utils import parseaddr
from .credentials import TokenStore, private_directory
from .data import integration_demo

LOCAL_TZ = timezone(timedelta(hours=5, minutes=30), 'Asia/Colombo')
SCOPES = {'gmail': 'https://www.googleapis.com/auth/gmail.readonly',
          'calendar': 'https://www.googleapis.com/auth/calendar.events.readonly'}
HOSTS = {'oauth2.googleapis.com', 'gmail.googleapis.com', 'www.googleapis.com',
         'en.wikipedia.org', 'api.search.brave.com'}

class IntegrationError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise IntegrationError('network', 'A provider redirect was blocked to protect credentials.')


def safe_public_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
            return None
        host = parsed.hostname.lower()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '.' not in host or host.endswith(('.local', '.localhost', '.internal')) or re.fullmatch(r'[\d.]+', host):
            return None
        return value
    except ValueError:
        return None


def plain(value, limit=300):
    return html.unescape(re.sub(r'<[^>]*>', '', value if isinstance(value, str) else ''))[:limit]


class Integrations:
    def __init__(self, index, *, store=None):
        self.index = index
        self.source = index.source
        self.store = store or TokenStore()
        self.opener = urllib.request.build_opener(NoRedirect())
        self.pending = {}
        self.lock = threading.RLock()
        self.last = {}
        self.client_id = os.environ.get('JARVIS_GOOGLE_CLIENT_ID', '')
        self.client_secret = os.environ.get('JARVIS_GOOGLE_CLIENT_SECRET', '')
        self.provider = os.environ.get('JARVIS_SEARCH_PROVIDER', '').lower()
        self.search_key = os.environ.get('BRAVE_SEARCH_API_KEY', '')

    def now(self):
        return datetime.now(LOCAL_TZ)

    def status(self):
        # Demo mode must not load or inspect real account credentials.
        configured = bool(self.client_id and self.client_secret)
        services = {service: {'authorization_saved': False if self.source.demo else self.store.has(service),
                             'last_request': self.last.get(service), 'scope': scope} for service, scope in SCOPES.items()}
        return {'demo': self.source.demo, 'google_configured': configured,
                'google_client_file_available': False if self.source.demo else (private_directory() / 'oauth-client.json').is_file(),
                'services': services, 'search_provider': self.provider or None,
                'search_configured': self.provider == 'wikipedia' or (self.provider == 'brave' and bool(self.search_key)),
                'token_storage': 'Windows DPAPI' if os.name == 'nt' else 'Memory only; lost on restart',
                'timezone': 'Asia/Colombo'}

    def real_only(self):
        if self.source.demo:
            raise IntegrationError('demo_blocked', 'Real account authorization and external research are blocked in demo mode, Shaheem.')

    def _json(self, url, *, form=None, headers=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:
            raise IntegrationError('validation', 'Unsupported provider destination')
        payload = urllib.parse.urlencode(form).encode() if form is not None else None
        request = urllib.request.Request(url, data=payload, headers={'User-Agent':'JARVIS-Local/0.5', **(headers or {})})
        if payload is not None:
            request.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise IntegrationError('provider', 'Provider response exceeded the safe size limit')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('Expected object')
            return result
        except urllib.error.HTTPError as error:
            if error.code in {400, 401, 403}:
                raise IntegrationError('authorization', 'Provider authorization was denied, expired, or lacks the required read-only permission. Reconnect through account settings.') from error
            if error.code == 429:
                raise IntegrationError('rate_limit', 'The provider rate limit was reached. No automatic retry was made.') from error
            raise IntegrationError('provider', f'The provider returned HTTP {error.code}. No successful result is claimed.') from error
        except (OSError, ValueError) as error:
            raise IntegrationError('network', 'The provider is unreachable or returned invalid data. Check network access and configuration.') from error

    def client(self):
        if self.client_id and self.client_secret:
            return self.client_id, self.client_secret
        path = private_directory() / 'oauth-client.json'
        self.store.safe_path(path)
        try:
            if path.stat().st_size > 65536:
                raise ValueError('Client file too large')
            data = json.loads(path.read_text(encoding='utf-8'))['installed']
            client_id, client_secret = data['client_id'], data['client_secret']
            if not isinstance(client_id, str) or not isinstance(client_secret, str) or not client_id or not client_secret:
                raise ValueError('Missing client fields')
            return client_id, client_secret
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise IntegrationError('configuration', 'Configure a Google Desktop OAuth client in the private auth folder or server environment. Never provide a Google password.') from error

    def begin(self, service, session, port, *, approved=False):
        self.real_only()
        if service not in SCOPES or approved is not True:
            raise IntegrationError('approval_required', 'Choose Gmail or Calendar and explicitly approve starting its separate Google OAuth flow.')
        client_id, _ = self.client()
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        redirect = f'http://127.0.0.1:{port}/oauth/google/callback'
        with self.lock:
            self.pending = {key:value for key,value in self.pending.items() if value['expires'] > time.monotonic()}
            if len(self.pending) >= 16:
                raise IntegrationError('busy', 'Too many authorization attempts. Wait for existing attempts to expire.')
            self.pending[state] = {'service':service, 'session':session, 'verifier':verifier, 'redirect':redirect,
                                   'expires':time.monotonic()+300, 'client_id':client_id}
        query = urllib.parse.urlencode({'client_id':client_id, 'redirect_uri':redirect, 'response_type':'code',
                    'scope':SCOPES[service], 'state':state, 'code_challenge':challenge, 'code_challenge_method':'S256',
                    'access_type':'offline', 'prompt':'consent', 'include_granted_scopes':'false'})
        return {'ok':True,'spoken':'Review the separate Google read-only consent screen, Shaheem.',
                'authorization_url':'https://accounts.google.com/o/oauth2/v2/auth?'+query, 'service':service}

    def finish(self, params):
        self.real_only()
        if set(params) - {'state','code','error','scope','authuser','prompt','error_description'} or len(params.get('state',[])) != 1:
            raise IntegrationError('oauth_state', 'Invalid OAuth callback')
        with self.lock:
            pending = self.pending.pop(params['state'][0], None)
            if not pending or pending['expires'] < time.monotonic():
                raise IntegrationError('oauth_state', 'OAuth state is invalid, expired or already used. Start again from JARVIS.')
            if 'error' in params:
                raise IntegrationError('authorization', 'Google authorization was declined or failed. No account was connected.')
            if len(params.get('code',[])) != 1 or not 1 <= len(params['code'][0]) <= 4096:
                raise IntegrationError('authorization', 'Google returned no usable authorization code')
            client_id, client_secret = self.client()
            if client_id != pending['client_id']:
                raise IntegrationError('configuration', 'OAuth client changed during authorization; start again.')
            token = self._json('https://oauth2.googleapis.com/token', form={'code':params['code'][0],
                'client_id':client_id, 'client_secret':client_secret, 'redirect_uri':pending['redirect'],
                'grant_type':'authorization_code','code_verifier':pending['verifier']})
            token = self.validate_token(token, pending['service'])
            self.store.save(pending['service'], token)
        return pending['service']

    def validate_token(self, token, service, previous=None):
        if not isinstance(token, dict) or not isinstance(token.get('access_token'), str) or not 1 <= len(token['access_token']) <= 12000 or str(token.get('token_type','')).lower() != 'bearer':
            raise IntegrationError('authorization', 'Google returned an invalid token response')
        scopes = token.get('scope', SCOPES[service])
        if not isinstance(scopes, str) or set(scopes.split()) != {SCOPES[service]}:
            raise IntegrationError('scope', 'Google did not grant exactly the requested read-only scope. Review the grant and reconnect.')
        try:
            expires = int(token.get('expires_in'))
            if not 1 <= expires <= 86400:
                raise ValueError('Invalid expiry')
        except (ValueError, TypeError) as error:
            raise IntegrationError('authorization','Invalid token expiry') from error
        refresh = token.get('refresh_token') or (previous or {}).get('refresh_token')
        if refresh is not None and (not isinstance(refresh,str) or len(refresh)>12000):
            raise IntegrationError('authorization','Invalid refresh token')
        return {'access_token':token['access_token'], 'refresh_token':refresh, 'expires_at':time.time()+expires, 'scope':SCOPES[service]}

    def access(self, service):
        self.real_only()
        with self.lock:
            try:
                token = self.store.load(service)
            except (OSError, ValueError) as error:
                raise IntegrationError('storage','Authorization could not be decrypted/read. Reconnect this account on your Windows user profile.') from error
            if not token or token.get('scope') != SCOPES[service]:
                raise IntegrationError('authorization',f'{service.title()} is not connected. Use its separate read-only Google authorization flow.')
            try:
                valid = float(token.get('expires_at',0)) > time.time()+60
            except (ValueError,TypeError):
                valid = False
            if not valid:
                if not token.get('refresh_token'):
                    raise IntegrationError('authorization','Authorization expired; reconnect this account.')
                client_id, client_secret = self.client()
                response = self._json('https://oauth2.googleapis.com/token',form={'client_id':client_id,'client_secret':client_secret,
                    'refresh_token':token['refresh_token'],'grant_type':'refresh_token'})
                token = self.validate_token(response,service,token)
                self.store.save(service,token)
            return token['access_token']

    def disconnect(self, service, session):
        self.real_only()
        if service not in SCOPES:
            raise ValueError('Unsupported service')
        with self.lock:
            self.store.delete(service)
            self.pending = {key:value for key,value in self.pending.items() if value['service'] != service}
            self.last.pop(service,None)
        return {'ok':True,'tool':'disconnect','spoken':f'{service.title()} authorization removed from JARVIS, Shaheem. Google account grants must be revoked separately in Google account permissions.'}

    def sender_evidence(self, sender):
        address = parseaddr(sender)[1].casefold()
        if not address or '@' not in address:
            return []
        pattern = re.compile(r'(?<![\w.+-])'+re.escape(address)+r'(?![\w.+-])',re.IGNORECASE)
        evidence = []
        for filename, doc in self.index.documents.items():
            for number,line in enumerate(doc.text.splitlines(),1):
                if pattern.search(line):
                    evidence.append({'filename':filename,'line':number,'citation':f'{filename}:{number}','excerpt':line[:160]})
                    break
            if len(evidence)>=3:
                break
        return evidence

    def inbox(self):
        if self.source.demo:
            return {'ok':True,'tool':'read_inbox','demo':True,'spoken':'Here is one fictional demo email, Shaheem. No real inbox was accessed.',
                    'emails':integration_demo(self.source,now=self.now())['emails'],'has_more':False}
        try:
            token = self.access('gmail')
            headers = {'Authorization':'Bearer '+token}
            query = urllib.parse.urlencode({'labelIds':['INBOX','UNREAD'],'maxResults':5},doseq=True)
            listing = self._json('https://gmail.googleapis.com/gmail/v1/users/me/messages?'+query,headers=headers)
            emails = []
            messages = listing.get('messages',[])
            if not isinstance(messages,list):
                raise IntegrationError('provider','Gmail returned an invalid message list')
            for row in messages[:5]:
                message_id = row.get('id') if isinstance(row,dict) else None
                if not isinstance(message_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',message_id):
                    raise IntegrationError('provider','Gmail returned an invalid message identifier')
                query = urllib.parse.urlencode({'format':'metadata','metadataHeaders':['From','Subject']},doseq=True)
                message = self._json('https://gmail.googleapis.com/gmail/v1/users/me/messages/'+message_id+'?'+query,headers=headers)
                payload = message.get('payload',{})
                if not isinstance(payload,dict) or not isinstance(payload.get('headers',[]),list):
                    raise IntegrationError('provider','Gmail returned invalid message metadata')
                fields = {item['name'].lower(): item.get('value','') for item in payload.get('headers',[]) if isinstance(item,dict) and isinstance(item.get('name'),str)}
                sender = fields.get('from','')
                sender = sender[:300] if isinstance(sender,str) else ''
                emails.append({'sender':sender,'subject':fields.get('subject','')[:200] if isinstance(fields.get('subject',''),str) else '',
                    'excerpt':plain(message.get('snippet',''),240), 'sender_evidence':self.sender_evidence(sender)})
            self.last['gmail']='success'
            return {'ok':True,'tool':'read_inbox','demo':False,'spoken':f'{len(emails)} unread inbox messages shown, Shaheem.',
                    'emails':emails,'has_more':bool(listing.get('nextPageToken'))}
        except IntegrationError:
            self.last['gmail']='error'
            raise

    def calendar(self, *, horizon='today', query=''):
        if horizon not in {'today','upcoming'} or not isinstance(query,str) or len(query)>300:
            raise ValueError('Choose today or upcoming and a query up to 300 characters')
        if self.source.demo:
            rows = integration_demo(self.source,now=self.now())['events']
            rows = [row for row in rows if query.casefold() in row['title'].casefold()]
            return {'ok':True,'tool':'google_calendar','demo':True,'spoken':f'{len(rows)} fictional calendar examples, Shaheem. No real calendar was accessed.',
                    'events':rows,'has_more':False,'timezone':'Asia/Colombo'}
        try:
            token = self.access('calendar')
            now = self.now()
            start = datetime.combine(now.date(),daytime.min,LOCAL_TZ) if horizon=='today' else now
            end = datetime.combine(now.date()+timedelta(days=1),daytime.min,LOCAL_TZ) if horizon=='today' else now+timedelta(days=7)
            params = {'timeMin':start.isoformat(),'timeMax':end.isoformat(),'singleEvents':'true','orderBy':'startTime',
                      'maxResults':20,'timeZone':'Asia/Colombo','fields':'items(id,summary,start,end,status),nextPageToken'}
            if query:
                params['q']=query
            response = self._json('https://www.googleapis.com/calendar/v3/calendars/primary/events?'+urllib.parse.urlencode(params),headers={'Authorization':'Bearer '+token})
            items = response.get('items',[])
            if not isinstance(items,list):
                raise IntegrationError('provider','Calendar returned invalid events')
            rows = []
            for item in items[:20]:
                if not isinstance(item,dict) or item.get('status')=='cancelled':
                    continue
                if not isinstance(item.get('start',{}),dict) or not isinstance(item.get('end',{}),dict):
                    raise IntegrationError('provider','Calendar returned invalid event times')
                rows.append({'title':plain(item.get('summary',''),200) or '(Untitled event)',
                    'start':item.get('start',{}).get('dateTime') or item.get('start',{}).get('date',''),
                    'end':item.get('end',{}).get('dateTime') or item.get('end',{}).get('date','')})
            self.last['calendar']='success'
            return {'ok':True,'tool':'google_calendar','demo':False,'spoken':f'{len(rows)} calendar events shown, Shaheem.',
                    'events':rows,'has_more':bool(response.get('nextPageToken')),'timezone':'Asia/Colombo'}
        except IntegrationError:
            self.last['calendar']='error'
            raise

    def research(self, query, *, approved=False):
        self.real_only()
        if not isinstance(query,str) or not 1<=len(query.strip())<=300:
            raise ValueError('Research query must contain 1–300 characters')
        if self.provider not in {'wikipedia','brave'}:
            raise IntegrationError('configuration','Live web research is unavailable. Explicitly configure Wikipedia reference search or a Brave Search API provider.')
        if approved is not True:
            raise IntegrationError('approval_required','Approve sending this query to the configured provider. Brave requests may consume credits or incur charges.')
        if self.provider=='wikipedia':
            params = {'action':'query','format':'json','generator':'search','gsrsearch':query,'gsrlimit':5,
                      'prop':'extracts|info','exintro':1,'explaintext':1,'exchars':500,'inprop':'url'}
            data = self._json('https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode(params))
            pages = data.get('query',{}).get('pages',{})
            values = sorted((page for page in pages.values() if isinstance(page,dict)),key=lambda page:page.get('index',0) if isinstance(page.get('index',0),(int,float)) else 0) if isinstance(pages,dict) else []
            results = [{'title':plain(page.get('title',''),200),'url':page.get('fullurl'),
                        'excerpt':plain(page.get('extract',''),500)} for page in values[:5] if isinstance(page,dict)]
        else:
            if not self.search_key:
                raise IntegrationError('configuration','BRAVE_SEARCH_API_KEY is missing on the Python server.')
            data = self._json('https://api.search.brave.com/res/v1/web/search?'+urllib.parse.urlencode({'q':query,'count':5}),headers={'X-Subscription-Token':self.search_key})
            results = [{'title':plain(row.get('title',''),200),'url':row.get('url'),
                        'excerpt':plain(row.get('description',''),500)} for row in data.get('web',{}).get('results',[])[:5] if isinstance(row,dict)]
        results = [{**row,'url':safe_public_url(row['url'])} for row in results if safe_public_url(row['url'])]
        return {'ok':True,'tool':'research_web','spoken':f'{len(results)} cited public results, Shaheem. Review the sources for accuracy.',
                'web_results':results,'provider':self.provider,'retrieved_at':self.now().isoformat()}

    def brief(self, tasks=None, reminders=None):
        if self.source.demo:
            fixtures = integration_demo(self.source,now=self.now())
            return {'ok':True,'tool':'brief_me','demo':True,'spoken':'Your fictional demo briefing is ready, Shaheem. No real accounts were accessed.',
                    'sections':fixtures,'unavailable':[],'timezone':'Asia/Colombo','date':self.now().date().isoformat()}
        sections, unavailable = {'tasks':tasks or [],'reminders':reminders or []}, []
        for name, function, key in [('Calendar',self.calendar,'events'),('Gmail',self.inbox,'emails')]:
            try:
                outcome = function()
                sections[key]=outcome[key]
                if outcome.get('has_more'):
                    unavailable.append(f'{name}: more results exist than this briefing displays.')
            except IntegrationError as error:
                sections[key]=[]
                unavailable.append(name+': '+str(error))
        if not tasks:
            unavailable.append('Tasks: none supplied in this session; no tasks or deadlines inferred.')
        if reminders is None:
            unavailable.append('Reminders: no approved reminder source was provided.')
        return {'ok':True,'tool':'brief_me','demo':False,'spoken':'Your available briefing sections are ready, Shaheem. Missing sources are listed explicitly.',
                'sections':sections,'unavailable':unavailable,'timezone':'Asia/Colombo','date':self.now().date().isoformat()}
