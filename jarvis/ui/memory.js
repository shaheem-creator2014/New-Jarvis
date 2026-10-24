const $ = id => document.getElementById(id);

export class MemoryController {
    constructor({request, onError, beforeOpen, isBusy}) {
        Object.assign(this,{request,onError,beforeOpen,isBusy});
        $('memory-open').onclick = () => this.open();
        $('memory-close').onclick = () => $('memory-dialog').close();
        $('memory-refresh').onclick = () => this.refresh();
        $('memory-form').onsubmit = async event => {
            event.preventDefault();
            if (isBusy()) return;
            try {
                const outcome = await request('/api/memory/run',{action:'save',fact:$('memory-fact').value.trim(),
                    approved:$('memory-approval').checked,sensitive:$('memory-sensitive').checked,
                    sensitive_approved:$('memory-sensitive-approval').checked,kind:$('memory-kind').value});
                if (!outcome.ok) throw new Error(outcome.spoken);
                $('memory-notice').textContent = outcome.spoken;
                $('memory-fact').value = '';
                $('memory-approval').checked = false;
                $('memory-sensitive-approval').checked = false;
                await this.refresh(false);
            } catch(error) { $('memory-notice').textContent=error.message;this.onError(error.message); }
        };
    }

    async open(fact='',sensitive=false) {
        if (this.isBusy()) return;
        this.beforeOpen();
        $('memory-fact').value = fact;
        $('memory-sensitive').checked = sensitive;
        $('memory-approval').checked = false;
        $('memory-sensitive-approval').checked = false;
        $('memory-kind').value = 'fact';
        $('memory-dialog').showModal();
        await this.refresh();
    }

    async refresh(resetNotice=true) {
        if (this.isBusy()) return;
        try {
            const outcome = await this.request('/api/memory/run',{action:'list'});
            if (!outcome.ok) throw new Error(outcome.spoken);
            $('memory-mode').textContent = outcome.demo ? 'DEMO MEMORIES · separate from real memory. Use fictional test facts here.' : 'REAL MEMORIES · local dated Markdown files. These files are not encrypted; do not store credentials.';
            if (resetNotice) $('memory-notice').textContent = outcome.spoken;
            $('memory-list').replaceChildren();
            for (const item of outcome.memories) {
                const card = document.createElement('article');
                const title=document.createElement('p'),fact=document.createElement('p'),button=document.createElement('button');
                title.className='small muted';title.textContent=`${item.id} · ${item.kind}${item.sensitive?' · sensitive':''}`;
                fact.textContent=item.fact;
                button.textContent='Delete this memory';
                button.onclick=async()=>{
                    if(this.isBusy()||!window.confirm('Delete this exact stored fact?\n\n'+item.fact))return;
                    try{
                        const deleted=await this.request('/api/memory/run',{action:'delete',id:item.id,approved:true});
                        if(!deleted.ok)throw new Error(deleted.spoken);
                        $('memory-notice').textContent=deleted.spoken;
                        // Remove stale recalled facts from this browser's conversation too.
                        $('history').replaceChildren();
                        await this.refresh(false);
                    }catch(error){$('memory-notice').textContent=error.message;this.onError(error.message);}
                };
                card.append(title,fact,button);$('memory-list').append(card);
            }
            for(const warning of outcome.warnings||[]){const p=document.createElement('p');p.textContent=warning;$('memory-list').append(p);}
        }catch(error){$('memory-notice').textContent=error.message;this.onError(error.message);}
    }

    render(outcome,card){
        if(outcome.needs_memory){
            const button=document.createElement('button');button.textContent='Review exact memory before saving';
            button.onclick=()=>this.open(outcome.fact,outcome.sensitive);card.append(button);
        }
        for(const item of outcome.memories||[]){
            const paragraph=document.createElement('p');paragraph.textContent=`[${item.id}] ${item.fact}`;card.append(paragraph);
        }
    }
}
