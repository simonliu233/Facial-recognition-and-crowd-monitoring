"use strict";
(() => {
  const config = window.cameraConfig, byId = id => document.getElementById(id);
  const video = byId("sourceVideo"), canvas = byId("preview"), ctx = canvas.getContext("2d");
  const raw = document.createElement("canvas"), rawCtx = raw.getContext("2d");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let media = null, objectURL = null, running = false, generation = 0;
  let streamId = "", frameIndex = 0, result = null, settings = null;
  let frameTimer = null, renderId = null, processing = Promise.resolve(), fileMode = false, fileTime = 0;

  function status(message, error = false) {
    byId("status").textContent = message;
    byId("status").classList.toggle("error", error);
  }
  async function api(url, options = {}) {
    const response = await fetch(url, {...options, headers: {"X-CSRFToken": csrf, Accept: "application/json", ...options.headers}});
    let body;
    try { body = await response.json(); } catch { throw new Error("伺服器未回傳有效資料，請重新登入。"); }
    if (!response.ok) throw new Error(body.error || body.description || "操作失敗，請重新整理後再試。");
    return body;
  }
  function showCounts(data) {
    if (config.mode !== "flow") return;
    byId("forward").textContent = data.left_to_right;
    byId("backward").textContent = data.right_to_left;
    byId("forwardLabel").textContent = data.forward_label;
    byId("backwardLabel").textContent = data.backward_label;
    byId("sessionCounts").textContent = (data.session_left_to_right || 0) + " / " + (data.session_right_to_left || 0);
    settings = data;
  }
  function draw() {
    if (video.readyState >= 2 && canvas.width) ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const geometry = settings || result;
    if (config.mode === "flow" && geometry) {
      const horizontal = geometry.axis === "y", position = geometry.line_position, band = geometry.dead_band;
      const dimension = horizontal ? canvas.height : canvas.width;
      const transverse = horizontal ? canvas.width : canvas.height;
      const start = (geometry.roi_start || 0) * transverse, end = (geometry.roi_end ?? 1) * transverse;
      ctx.fillStyle = "rgba(104,223,192,.15)";
      if (horizontal) ctx.fillRect(start, (position-band)*dimension, end-start, 2*band*dimension);
      else ctx.fillRect((position-band)*dimension, start, 2*band*dimension, end-start);
      ctx.strokeStyle = "#68dfc0"; ctx.lineWidth = 3; ctx.beginPath();
      if (horizontal) {ctx.moveTo(start, position*dimension); ctx.lineTo(end, position*dimension);}
      else {ctx.moveTo(position*dimension, start); ctx.lineTo(position*dimension, end);}
      ctx.stroke();
    }
    for (const box of (result?.boxes || result?.faces || [])) {
      ctx.strokeStyle = config.mode === "flow" ? "#68dfc0" : "#ffcc75";
      ctx.lineWidth = 2; ctx.strokeRect(box.x, box.y, box.w, box.h);
      const label = config.mode === "flow" ? "ID " + box.id : box.name + " " + Math.round(box.confidence*100) + "%";
      ctx.font = "16px sans-serif";
      const textWidth = ctx.measureText(label).width;
      const textY = Math.max(22, box.y);
      ctx.fillStyle = "rgba(5,15,25,.85)"; ctx.fillRect(box.x, textY-22, textWidth+12, 24);
      ctx.fillStyle = "#fff"; ctx.fillText(label, box.x+5, textY-4);
      if (config.mode === "flow") {
        ctx.beginPath();ctx.arc(box.x+box.w/2, box.y+box.h, 4, 0, Math.PI*2);ctx.fillStyle="#ffcc75";ctx.fill();
      }
    }
    if (running) renderId = requestAnimationFrame(draw);
  }
  function initializeDimensions() {
    const scale = Math.min(1, 960/video.videoWidth);
    canvas.width = raw.width = Math.round(video.videoWidth*scale);
    canvas.height = raw.height = Math.round(video.videoHeight*scale);
  }
  async function stop(message = "已停止；目前紀錄已儲存在本機。") {
    running = false; generation++;
    clearTimeout(frameTimer);cancelAnimationFrame(renderId);
    if (media) {media.getTracks().forEach(track=>track.stop());media=null;}
    video.pause();
    byId("stopCamera").disabled = true;
    await processing.catch(()=>{});
    if (streamId && config.mode === "flow") {
      const body = new FormData();body.append("stream_id",streamId);
      try {await api(config.stop,{method:"POST",body});} catch(e) {console.warn(e);}
    }
    video.srcObject = null;
    if (objectURL) {URL.revokeObjectURL(objectURL);objectURL=null;video.removeAttribute("src");}
    byId("startCamera").disabled = false;
    byId("videoFile").disabled = false;
    streamId="";
    status(message);
  }
  function waitForMedia(event) {
    return new Promise((resolve,reject)=>{
      const ok=()=>{cleanup();resolve();}, bad=()=>{cleanup();reject(new Error("無法讀取這個影片格式。"));};
      const cleanup=()=>{video.removeEventListener(event,ok);video.removeEventListener("error",bad);};
      video.addEventListener(event,ok,{once:true});video.addEventListener("error",bad,{once:true});
    });
  }
  async function seekFile(time) {
    if (Math.abs(video.currentTime-time)<0.0001 && video.readyState>=2) return;
    const wait=waitForMedia("seeked");video.currentTime=time;await wait;
  }
  async function runFrame(token) {
    if (!running || token !== generation) return;
    const started = performance.now();
    try {
      if (fileMode) await seekFile(fileTime);
      if (!running || token !== generation) return;
      rawCtx.drawImage(video,0,0,raw.width,raw.height);
      const blob=await new Promise(resolve=>raw.toBlob(resolve,"image/jpeg",0.9));
      if (!blob) throw new Error("無法擷取影格。");
      const body=new FormData();body.append("image",blob,"frame.jpg");
      body.append("stream_id",streamId);body.append("frame_index",String(++frameIndex));
      const data=await api(config.endpoint,{method:"POST",body});
      if (!running || token !== generation) return;
      result=data;showCounts(data);
      const elapsed=performance.now()-started, fps=1000/elapsed;
      if(config.mode==="flow") {
        byId("details").textContent="追蹤 "+data.active_tracks+" 人 · 分析 "+fps.toFixed(1)+" FPS · 本次越線 "+data.events.length+" 次";
      } else {
        const faces=data.faces.map(f=>f.name+" · "+f.age+" 歲 · "+f.gender+" · "+f.emotion).join("；");
        byId("details").textContent="已載入 "+data.gallery_size+" 個人臉特徵；"+(faces||"未偵測到人臉。")+
          (data.gallery_warnings.length ? "；略過 "+data.gallery_warnings.length+" 張無法編碼的範例照片。" : "")+
          (data.emotion_available ? "" : "；情緒模型未啟用。");
      }
      status(fileMode ? "本機影片分析中 · "+fileTime.toFixed(1)+" / "+video.duration.toFixed(1)+" 秒" : "攝影機分析中 · "+fps.toFixed(1)+" FPS");
      if(fileMode) {
        fileTime+=1/Number(byId("targetFps").value);
        if(fileTime>=video.duration) {
          // Do not await stop() inside processing: it waits for this very promise.
          setTimeout(()=>stop("影片分析完成；本次及今日計數已保留。"),0);
          return;
        }
      }
      frameTimer=setTimeout(scheduleFrame,Math.max(0,1000/Number(byId("targetFps").value)-elapsed));
    } catch(error) {
      running=false;generation++;clearTimeout(frameTimer);
      setTimeout(async()=>{await stop();status(error.message,true);},0);
    }
  }
  function scheduleFrame() {const token=generation;processing=runFrame(token);}
  async function start(file=null) {
    await stop();
    try {
      status("正在啟動；首次載入模型可能需等待一段時間。");
      byId("startCamera").disabled=true;byId("videoFile").disabled=true;
      fileMode=Boolean(file);fileTime=0;frameIndex=0;result=null;
      streamId=crypto.randomUUID ? crypto.randomUUID() : String(Date.now())+Math.random();
      if(file) {
        objectURL=URL.createObjectURL(file);
        const metadata=waitForMedia("loadeddata");video.src=objectURL;video.load();await metadata;
        if(!Number.isFinite(video.duration)||video.duration<=0)throw new Error("影片長度無效。");
        video.pause();
      } else {
        if(!navigator.mediaDevices?.getUserMedia)throw new Error("請用本機 localhost 網址及支援攝影機的瀏覽器。");
        const device=byId("cameraSelect").value;
        media=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720},...(device?{deviceId:{exact:device}}:{})},audio:false});
        video.srcObject=media;await video.play();
        const selected=byId("cameraSelect").value;
        const devices=await navigator.mediaDevices.enumerateDevices();
        byId("cameraSelect").replaceChildren(new Option("預設攝影機",""));
        devices.filter(d=>d.kind==="videoinput").forEach(d=>byId("cameraSelect").add(new Option(d.label||"攝影機",d.deviceId)));
        byId("cameraSelect").value=selected;
      }
      initializeDimensions();running=true;generation++;
      byId("stopCamera").disabled=false;draw();scheduleFrame();
    } catch(error) {await stop();status(error.message,true);}
  }
  byId("startCamera").onclick=()=>start();
  byId("stopCamera").onclick=()=>stop();
  byId("videoFile").onchange=event=>{const file=event.target.files[0];if(file)start(file);event.target.value="";};
  if(config.mode==="flow") {
    api(config.stats).then(data=>{
      showCounts(data);byId("axis").value=data.axis;byId("linePosition").value=data.line_position*100;
      byId("deadBand").value=data.dead_band*100;byId("roiStart").value=data.roi_start*100;byId("roiEnd").value=data.roi_end*100;
      draw();
    }).catch(error=>status(error.message,true));
    byId("flowSettings").onsubmit=async event=>{
      event.preventDefault();await stop();
      try {
        const data=await api(config.settings,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
          axis:byId("axis").value,line_position:Number(byId("linePosition").value)/100,dead_band:Number(byId("deadBand").value)/100,
          roi_start:Number(byId("roiStart").value)/100,roi_end:Number(byId("roiEnd").value)/100})});
        result=null;showCounts(data);ctx.clearRect(0,0,canvas.width,canvas.height);draw();status("設定已儲存。請重新開始攝影機或選擇影片。");
      }catch(error){status(error.message,true);}
    };
    byId("resetCounts").onclick=async()=>{
      if(!confirm("清除今日所有人流計數及越線事件？歷史其他日期不受影響。"))return;
      await stop();try {showCounts(await api(config.reset,{method:"POST"}));status("今日計數已清除。");}
      catch(error){status(error.message,true);}
    };
  }
  window.addEventListener("pagehide",()=>{
    running=false;media?.getTracks().forEach(track=>track.stop());
    if(streamId&&config.mode==="flow") {
      const body=new FormData();body.append("stream_id",streamId);body.append("csrf_token",csrf);
      navigator.sendBeacon(config.stop,body);
    }
  });
})();
