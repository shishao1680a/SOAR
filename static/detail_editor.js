let currentDetailBlocks=[];
function loadDetailBlocks(p){
  try{currentDetailBlocks=JSON.parse(p?.detail_blocks_json||'[]');if(!Array.isArray(currentDetailBlocks))currentDetailBlocks=[]}catch(e){currentDetailBlocks=[]}
  document.getElementById('detail-preview').hidden=true;
  document.getElementById('detail-preview').replaceChildren();
  renderDetailBlocks();
}
function addDetailBlock(type){if(currentDetailBlocks.length>=100){alert('最多 100 段');return}currentDetailBlocks.push(type==='text'?{type,text:''}:{type,url:'',caption:''});renderDetailBlocks()}
function renderDetailBlocks(){
  const host=document.getElementById('detail-block-editor');host.replaceChildren();
  currentDetailBlocks.forEach((block,i)=>{
    const box=document.createElement('div');box.className='detail-editor-block';const title=document.createElement('strong');title.textContent=(i+1)+'. '+(block.type==='text'?'文字段落':'圖片段落');box.append(title);
    if(block.type==='text'){const input=document.createElement('textarea');input.rows=4;input.maxLength=10000;input.value=block.text||'';input.placeholder='輸入商品介紹，支援換行';input.setAttribute('aria-label','文字段落 '+(i+1));input.oninput=()=>block.text=input.value;box.append(input)}
    else{
      if(block.url){const img=document.createElement('img');img.src=block.url;img.alt=block.caption||'介紹圖片';box.append(img)}
      const file=document.createElement('input');file.type='file';file.accept='.jpg,.jpeg,.png,.webp,.gif';file.disabled=!!block.pending;file.setAttribute('aria-label','上傳圖片段落 '+(i+1));file.onchange=async()=>{
        if(!file.files[0])return;const chosen=file.files[0];block.pending=true;block.error='';renderDetailBlocks();
        try{const form=new FormData();form.append('file',chosen);form.append('require_cloud','1');const r=await fetch('/api/admin/upload-image',{method:'POST',body:form});const data=await r.json();if(!r.ok||data.status!=='success'||!data.is_cloud)throw Error(data.message||'雲端上傳失敗');block.url=data.url}
        catch(e){block.error=e.message||'上傳失敗，請重試'}finally{block.pending=false;renderDetailBlocks()}
      };const caption=document.createElement('input');caption.type='text';caption.maxLength=500;caption.value=block.caption||'';caption.placeholder='圖片說明（選填）';caption.setAttribute('aria-label','圖片說明 '+(i+1));caption.oninput=()=>block.caption=caption.value;box.append(file,caption);
      const status=document.createElement('p');status.textContent=block.pending?'圖片上傳中……':block.error||(!block.url?'請選擇圖片，上傳成功後才能儲存':'已存到雲端');status.setAttribute('role','status');box.append(status);
    }
    const controls=document.createElement('div');controls.className='detail-editor-controls';
    for(const [label,action,disabled] of [['上移',()=>{[currentDetailBlocks[i-1],currentDetailBlocks[i]]=[currentDetailBlocks[i],currentDetailBlocks[i-1]]},i===0],['下移',()=>{[currentDetailBlocks[i+1],currentDetailBlocks[i]]=[currentDetailBlocks[i],currentDetailBlocks[i+1]]},i===currentDetailBlocks.length-1],['移除',()=>currentDetailBlocks.splice(i,1),false]]){const b=document.createElement('button');b.type='button';b.textContent=label;b.disabled=disabled||currentDetailBlocks.some(x=>x.pending);b.onclick=()=>{action();renderDetailBlocks()};controls.append(b)}box.append(controls);host.append(box);
  });
}
function readyDetailBlocks(){return !currentDetailBlocks.some(b=>b.pending||b.error||(b.type==='image'&&!b.url))}
function serializeDetailBlocks(){return currentDetailBlocks.map(b=>b.type==='text'?{type:'text',text:b.text||''}:{type:'image',url:b.url,caption:b.caption||''})}
function previewDetailBlocks(){const host=document.getElementById('detail-preview');host.replaceChildren();for(const b of currentDetailBlocks){if(b.type==='text'){const p=document.createElement('p');p.style.whiteSpace='pre-wrap';p.textContent=b.text;host.append(p)}else if(b.url){const img=document.createElement('img');img.src=b.url;img.alt=b.caption||'';const p=document.createElement('p');p.textContent=b.caption;host.append(img,p)}}host.hidden=!host.hidden}
