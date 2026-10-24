// Connections are explicit. Demo data and account availability are never conflated.
const $ = id => document.getElementById(id);

export class IntegrationController {
    constructor({get, run, onError, isBusy, beforeOpen}) {
        Object.assign(this, {get, run, onError, isBusy, beforeOpen});
        $('connections-open').onclick = () => this.open();
        $('connections-close').onclick = () => $('connections-dialog').close();
        $('connections-refresh').onclick = () => this.refresh();
        $('brief-me').onclick = () => this.run('/api/integrations/run', {action:'brief_me'});
        $('inbox-read').onclick = () => this.launchRead({action:'read_inbox'});
        $('calendar-read').onclick = () => this.launchRead({action:'google_calendar',horizon:$('calendar-horizon').value,query:$('calendar-query').value.trim()});
        $('research-open').onclick = () => this.openResearch('');
        $('research-cancel').onclick = () => $('research-dialog').close();
        $('research-form').onsubmit = async event => {
            event.preventDefault();
            if (!isBusy() && $('research-approval').checked) {
                const query = $('research-query').value.trim();
                if (!query) return;
                $('research-dialog').close();
                await run('/api/integrations/run',{action:'research_web',query,approved:true});
            }
        };
        for (const service of ['gmail','calendar']) {
            $(service+'-connect').onclick = async () => {
                if (isBusy()) return;
                if (!$('oauth-approval').checked) {
                    $('connection-notice').textContent = 'Explicitly approve starting the separate Google authorization flow first.';
                    return;
                }
                $('connections-dialog').close();
                await run('/api/oauth/begin',{service,approved:true});
            };
            $(service+'-disconnect').onclick = async () => {
                if (isBusy()) return;
                if (!window.confirm('Remove this saved authorization and clear retrieved account data from JARVIS? Google account grants must be revoked separately.')) return;
                $('connections-dialog').close();
                await run('/api/oauth/disconnect',{service,approved:true});
            };
        }
        this.refresh();
    }

    async refresh() {
        try {
            const status = await this.get('/api/integrations/status');
            this.status = status;
            $('connection-notice').textContent = status.demo ? 'FICTIONAL DEMO: Inbox, Calendar and Brief use sample data. Real OAuth and external research are blocked.' : 'Real mode: authorize each account separately. Only read-only permissions are requested.';
            $('token-storage').textContent = status.token_storage;
            $('google-configuration').textContent = status.google_configured || status.google_client_file_available ? 'Desktop client configured; authorization is separate.' : 'Google Desktop client is missing. See README for private configuration.';
            $('research-provider').textContent = status.search_provider ? `${status.search_provider} · ${status.search_configured?'configured':'missing configuration'}` : 'Not configured — live research unavailable';
            let saved = 0;
            for (const service of ['gmail','calendar']) {
                const info = status.services[service];
                saved += Number(info.authorization_saved);
                $(service+'-status').textContent = status.demo ? 'Demo only' : info.last_request==='success' ? 'Last read succeeded' : info.last_request==='error' ? 'Last read failed' : info.authorization_saved ? 'Authorization saved · unverified' : 'Not connected';
                $(service+'-connect').disabled = status.demo;
                $(service+'-disconnect').disabled = status.demo || !info.authorization_saved;
            }
            $('google-state').textContent = status.demo ? 'Demo only' : `${saved}/2 authorizations saved`;
        } catch (error) {
            $('connection-notice').textContent = 'Connection status could not be loaded: '+error.message;
        }
    }

    async open() {
        if (this.isBusy()) return;
        this.beforeOpen();
        await this.refresh();
        $('oauth-approval').checked = false;
        $('connections-dialog').showModal();
    }

    async launchRead(body) {
        if (this.isBusy()) return;
        $('connections-dialog').close();
        await this.run('/api/integrations/run',body);
    }

    async openResearch(query) {
        if (this.isBusy()) return;
        this.beforeOpen();
        await this.refresh();
        $('research-query').value = query;
        $('research-approval').checked = false;
        $('research-dialog').showModal();
    }

    render(outcome, card) {
        const append = (tag, text) => {
            const element = document.createElement(tag);
            element.textContent = text;
            card.append(element);
            return element;
        };
        if (outcome.demo) append('p','FICTIONAL DEMO — no real account data.');
        if (outcome.authorization_url) {
            const url = new URL(outcome.authorization_url);
            if (url.origin==='https://accounts.google.com' && url.pathname==='/o/oauth2/v2/auth') {
                const link = append('a','Continue to Google read-only consent');
                link.href = url.href;link.target='_blank';link.rel='noopener noreferrer';
                append('p','Use the browser on the PC running JARVIS. A cloud server’s loopback callback cannot be reached from your PC. Return here and refresh Connections afterward.');
            }
        }
        const renderEmails = emails => {
            append('h3','Unread inbox messages');
            if (!emails.length) append('p','No messages shown. Check source availability below.');
            for (const email of emails) {
                append('p',`${email.sender} · ${email.subject || '(No subject)'}`);
                const details = document.createElement('details');
                const summary = document.createElement('summary');summary.textContent='Show message excerpt and sender evidence';
                details.append(summary);card.append(details);
                const snippet = document.createElement('p');snippet.textContent=email.excerpt;details.append(snippet);
                const evidence = document.createElement('p');
                evidence.textContent = email.sender_evidence?.length ? 'Exact sender-address matches in indexed notes: '+email.sender_evidence.map(row=>`${row.citation} — ${row.excerpt}`).join('; ') : 'No exact sender-address evidence in indexed notes. This does not establish whether you know the sender.';
                details.append(evidence);
            }
        };
        const renderEvents = events => {
            append('h3','Calendar · Asia/Colombo');
            if (!events.length) append('p','No events shown. Check source availability below.');
            for (const event of events) {
                const format = value => {
                    if (!value || !value.includes('T')) return value || 'Time not provided';
                    const parsed = new Date(value);
                    return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString('en-GB',{timeZone:'Asia/Colombo',dateStyle:'medium',timeStyle:'short'});
                };
                append('p',`${event.title} · ${format(event.start)} → ${format(event.end)}${event.start && !event.start.includes('T') ? ' (all-day; end date exclusive)' : ''}`);
            }
        };
        if (outcome.emails) renderEmails(outcome.emails);
        if (outcome.events) renderEvents(outcome.events);
        if (outcome.sections) {
            append('p',`${outcome.date} · ${outcome.timezone}`);
            renderEvents(outcome.sections.events || []);
            renderEmails(outcome.sections.emails || []);
            append('h3','Supplied tasks');
            for (const task of outcome.sections.tasks || []) append('p',task.text);
            append('h3','Reminders');
            for (const reminder of outcome.sections.reminders || []) append('p',reminder);
            for (const unavailable of outcome.unavailable || []) append('p',unavailable);
        }
        if (outcome.has_more) append('p','More results exist than are shown here.');
        if (outcome.web_results) {
            append('p',`${outcome.provider} · retrieved ${outcome.retrieved_at}`);
            for (const row of outcome.web_results) {
                const url = new URL(row.url);
                if (url.protocol!=='https:' || url.username || url.password) continue;
                const link = append('a',row.title || row.url);
                link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';
                append('p',row.excerpt);
            }
            append('p','Provider excerpts are untrusted source material, not verified facts.');
        }
        if (outcome.needs_research) {
            const button = append('button','Review public research query');
            button.onclick = () => this.openResearch(outcome.query || '');
        }
        if (outcome.tool==='disconnect') {
            // Clear stale account cards immediately; server also purges account caches.
            $('history').replaceChildren(card);
        }
    }
}
