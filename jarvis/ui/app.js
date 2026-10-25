import {Graph,COLORS} from './graph.js';
import {VoiceController} from './voice.js';
import {IntegrationController} from './integrations.js';
import {MemoryController} from './memory.js';
const $=id=>document.getElementById(id);
function state(value){$('reactor').dataset.state=value;$('reactor-label').textContent={idle:'IDLE / READY',thinking:'PROCESSING REQUEST',listening:'LISTENING',speaking:'SPEAKING',error:'ERROR / ATTENTION'}[value];}
function error(message){$('error').textContent=message;$('error').hidden=false;state('error');}
function nodeButton(node,select){const button=document.createElement('button');button.className='node-button';const label=document.createElement('span');label.textContent=node.title;const count=document.createElement('b');count.textContent=node.connections;button.append(label,count);button.onclick=e=>select(node.id,e.shiftKey);return button;}
function message(text,type='system'){const div=document.createElement('div');div.className=`message ${type}`;div.textContent=text;$('history').append(div);while($('history').children.length>40)$('history').firstChild.remove();$('history').scrollTop=$('history').scrollHeight;return div;}
async function get(url){const response=await fetch(url,{credentials:'same-origin'});const data=await response.json();if(!response.ok)throw new Error(data.error||`Request failed (${response.status})`);return data;}
try{
 const data=await get('/api/graph');const byId=new Map(data.nodes.map(n=>[n.id,n]));let graph;
 function inspect(node){$('selected-kind').textContent=`${node.type.toUpperCase()} / ${node.category.replaceAll('_',' ')}`;$('selected-title').textContent=node.title;$('selected-hint').textContent='Selected source · read-only';$('details').replaceChildren();for(const [term,value]of [['LOCATION',node.id],['CONNECTIONS',String(node.connections)]]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=term;dd.textContent=value;$('details').append(dt,dd);}$('summary').textContent='SOURCE EXCERPT · '+node.summary;$('related').replaceChildren();const heading=document.createElement('h3');heading.textContent='RELATED DOCUMENTS';$('related').append(heading);for(const related of node.related.map(id=>byId.get(id)).sort((a,b)=>b.connections-a.connections))$('related').append(nodeButton(related,(id,shift)=>graph.select(id,shift)));$('path').textContent='';}
 graph=new Graph($('graph'),data,inspect,path=>{$('path').textContent=path.length?`SHORTEST PATH · ${path.length-1} links\n${path.map(id=>byId.get(id).title).join(' → ')}`:'No path connects these documents.';});
 $('animation').setAttribute('aria-pressed',String(graph.motion));
 $('mode').textContent=data.demo?'FICTIONAL DEMO':'REAL KNOWLEDGE';$('privacy').textContent=data.demo?'Fictional sample documents. No accounts connected.':'Approved local documents. No accounts connected.';$('server-state').textContent='Connected';$('documents').textContent=data.nodes.length;$('connections').textContent=data.edges.length;$('graph-description').textContent=`${data.nodes.length} documents. ${data.edges.length} connections. One connected perspective.`;
 if(data.warnings.length||data.skipped.length)message([...data.warnings,`${data.skipped.length} files skipped during indexing.`].join(' '));
 function counts(){$('visible-count').textContent=`${graph.nodes.filter(n=>graph.visible(n)).length} VISIBLE NODES / ${data.nodes.length} INDEXED`;}
 for(const node of [...data.nodes].sort((a,b)=>b.connections-a.connections||a.id.localeCompare(b.id)).slice(0,10))$('hubs').append(nodeButton(node,(id,shift)=>graph.select(id,shift)));
 for(const category of graph.categories){const label=document.createElement('label');label.className='filter';const input=document.createElement('input');input.type='checkbox';input.checked=true;const swatch=document.createElement('span');swatch.className='swatch';swatch.style.backgroundColor=COLORS[category]||'#ddd';const name=document.createElement('span');name.textContent=category.replaceAll('_',' ');const count=document.createElement('b');count.textContent=data.nodes.filter(n=>n.category===category).length;label.append(input,swatch,name,count);input.onchange=()=>{if(input.checked)graph.categories.add(category);else graph.categories.delete(category);graph.dirty=true;counts();};$('filters').append(label);}
 counts();$('fit').onclick=()=>graph.fit();$('labels').onclick=()=>{graph.labels=!graph.labels;$('labels').setAttribute('aria-pressed',String(graph.labels));graph.dirty=true;};$('animation').onclick=()=>{graph.motion=!graph.motion;if(graph.motion)graph.energy=180;$('animation').setAttribute('aria-pressed',String(graph.motion));graph.dirty=true;};

 let csrf='',busy=false,preparedTasks=[],voice,integrations,memory;
 async function voiceRequest(path,payload){
  if(busy)throw new Error('JARVIS is busy. Wait before retrying.');
  busyState(true);$('error').hidden=true;state('thinking');
  try {
   const accepted=await post(path,payload);
   for(let attempt=0;attempt<130;attempt++){
    await new Promise(resolve=>setTimeout(resolve,500));
    const job=await get('/api/jobs/'+encodeURIComponent(accepted.job));
    if(job.state==='done')return job.result;
   }
   throw new Error('Voice request is still running. It may have consumed credits; do not retry automatically.');
  }finally{busyState(false);if($('reactor').dataset.state==='thinking')state('idle');}
 }
 const session=await get('/api/session');csrf=session.csrf;
 if(session.history.length){$('history').replaceChildren();for(const item of session.history)message(item.content,item.role==='user'?'user':'system');}
 async function post(path,body){const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Jarvis-CSRF':csrf},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw new Error(value.error||`Request failed (${response.status})`);return value;}
 voice=new VoiceController({request:voiceRequest,onText:async text=>{message(text,'user');return run('/api/chat',{text,mode:$('chat-mode').value});},onState:value=>{state(value);if(value==='listening'||value==='speaking')$('error').hidden=true;},onError:error,onMessage:text=>message(text),isBusy:()=>busy});
 async function checkAI(){ $('check-ai').disabled=true;try{const status=await get('/api/status');$('ollama-state').textContent=status.ollama.model_ready?'Ready':status.ollama.connected?'Model missing':'Unavailable';voice.configure(status.voice);$('ai-notice').textContent=status.ollama.model_ready?`Local model: ${status.ollama.model}. Voice is optional; each paid request needs approval.`:`Limited mode: ${status.ollama.message} Use File search mode or /help.`;}catch(err){$('ollama-state').textContent='Status failed';$('ai-notice').textContent=err.message;}finally{$('check-ai').disabled=false;}}
 memory=new MemoryController({request:voiceRequest,onError:error,isBusy:()=>busy,beforeOpen:()=>voice.interrupt()});
 integrations=new IntegrationController({get,run,onError:error,isBusy:()=>busy,beforeOpen:()=>voice.interrupt()});
 $('check-ai').onclick=checkAI;checkAI();
 function busyState(value){busy=value;$('send').disabled=value;$('plan-day').disabled=value;$('clear-chat').disabled=value;$('make-plan').disabled=value;$('brief-me').disabled=value;for(const id of ['memory-open','memory-refresh','memory-save','connections-open','research-open'])$(id).disabled=value;$('chat-engine').textContent=value?'PROCESSING · YOUR LOCAL REQUEST IS RUNNING':'TEXT CHAT · /help FOR EXPLICIT COMMANDS';}
 function render(outcome,jobId){const card=message(outcome.spoken||'No response was returned.');const engine=document.createElement('span');engine.className='engine';engine.textContent=outcome.engine||outcome.tool||'JARVIS';card.prepend(engine);
 integrations.render(outcome,card);
 memory.render(outcome,card);
 for(const row of outcome.results||[]){const button=document.createElement('button');button.textContent=`${row.citation} — ${row.snippet}`;button.onclick=()=>graph.select(row.filename);card.append(button);}
 if(jobId&&outcome.spoken){const speak=document.createElement('button');speak.textContent='Speak response (credits)';speak.onclick=()=>voice.speak(jobId);card.append(speak);}
 if(outcome.help){const hint=document.createElement('p');hint.textContent=outcome.help;card.append(hint);}
 if(outcome.needs_tasks){const button=document.createElement('button');button.textContent='Enter actual tasks';button.onclick=openPlan;card.append(button);}
 if(outcome.priorities){const list=document.createElement('ol');for(const item of outcome.priorities){const li=document.createElement('li');li.textContent=item.text+(item.urgent?' · marked time-sensitive':'');list.append(li);}card.append(list);const note=document.createElement('p');note.textContent=outcome.method;card.append(note);}
 if(outcome.confirmation){const confirmation=outcome.confirmation;const box=document.createElement('div');box.className='confirm-actions';const approve=document.createElement('button'),cancel=document.createElement('button');approve.textContent='Confirm action';cancel.textContent='Cancel';for(const [button,approved]of [[approve,true],[cancel,false]])button.onclick=async()=>{if(busy)return;approve.disabled=true;cancel.disabled=true;const done=await run('/api/confirm',{token:confirmation.token,approved});if(!done){approve.disabled=false;cancel.disabled=false;}};box.append(approve,cancel);card.append(box);setTimeout(()=>{approve.disabled=true;cancel.disabled=true;},confirmation.expires_in*1000);}
 if(outcome.ok===false){state('error');$('error').textContent=outcome.spoken;$('error').hidden=false;}else state('idle');$('history').scrollTop=$('history').scrollHeight;
 }
 async function run(path,payload){if(busy)return false;if(voice.recorder||voice.audio||voice.preparing)voice.interrupt();busyState(true);$('error').hidden=true;state('thinking');try{const accepted=await post(path,payload);for(let attempt=0;attempt<480;attempt++){if(attempt%10===0)$('chat-engine').textContent=`THINKING · ${Math.floor(attempt/2)}s · FIRST RESPONSE MAY LOAD THE MODEL`;await new Promise(resolve=>setTimeout(resolve,500));const job=await get('/api/jobs/'+encodeURIComponent(accepted.job));if(job.state==='done'){render(job.result,accepted.job);return {...job.result,job:accepted.job};}}throw new Error('The request is still running. Please wait before retrying; completion has not been confirmed.');}catch(err){error(err.message);message('Request failed: '+err.message);return false;}finally{busyState(false);}}
 $('command-form').onsubmit=async e=>{e.preventDefault();const text=$('command').value.trim();if(!text||busy)return;message(text,'user');$('command').value='';await run('/api/chat',{text,mode:$('chat-mode').value});};
 $('chat-mode').onchange=()=>{$('command').placeholder={chat:'Ask JARVIS, Shaheem…',search:'Search indexed words or filenames…',robotics:'Ask about Arduino, ESP32 or Python…'}[$('chat-mode').value];};
 $('clear-chat').onclick=async()=>{if(busy)return;voice.interrupt();try{await post('/api/clear',{});$('history').replaceChildren();message('Conversation and pending confirmations cleared, Shaheem.');$('error').hidden=true;state('idle');}catch(err){error(err.message);}};
 function openPlan(){if(busy)return;voice.interrupt();preparedTasks=[];$('task-lines').value='';$('task-lines').hidden=false;$('task-editor').replaceChildren();$('prepare-tasks').hidden=false;$('make-plan').hidden=true;$('plan-dialog').showModal();}
 $('plan-day').onclick=openPlan;$('plan-cancel').onclick=()=>$('plan-dialog').close();
 $('prepare-tasks').onclick=()=>{const lines=$('task-lines').value.split('\n').map(line=>line.trim()).filter(Boolean);if(lines.length<1||lines.length>30||lines.some(line=>line.length>300)){$('task-lines').setCustomValidity('Enter 1–30 tasks, each no longer than 300 characters.');$('task-lines').reportValidity();return;}$('task-lines').setCustomValidity('');preparedTasks=lines.map(text=>({text,category:'other',urgent:false}));$('task-editor').replaceChildren();for(const task of preparedTasks){const row=document.createElement('div');row.className='task-row';const text=document.createElement('p');text.textContent=task.text;const select=document.createElement('select');select.setAttribute('aria-label','Category for '+task.text);for(const name of ['other','school','commitment','robotics','website','content']){const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option);}select.onchange=()=>task.category=select.value;const urgent=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.onchange=()=>task.urgent=checkbox.checked;urgent.append(checkbox,document.createTextNode(' Time-sensitive'));row.append(text,select,urgent);$('task-editor').append(row);}$('task-lines').hidden=true;$('prepare-tasks').hidden=true;$('make-plan').hidden=false;};
 $('task-lines').oninput=()=>$('task-lines').setCustomValidity('');
 $('plan-form').onsubmit=async e=>{e.preventDefault();if(!preparedTasks.length||busy)return;const tasks=preparedTasks.map(task=>({...task}));$('plan-dialog').close();message('Plan my day using the tasks I supplied.','user');await run('/api/plan',{tasks});};

}catch(err){$('server-state').textContent='Unavailable';error('Cannot load knowledge: '+err.message);}
