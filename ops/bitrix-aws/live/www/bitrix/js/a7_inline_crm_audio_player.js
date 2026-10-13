(function(){
  if (window.A7InlineCrmAudioPlayerLoaded) { return; }
  window.A7InlineCrmAudioPlayerLoaded = true;
  var cssHref = '/bitrix/css/a7_inline_crm_audio_player.css?v=20260621a';
  var audioNamePattern = /\.(mp3|m4a|ogg|wav)(\s|$|\?)/i;

  function getDocuments() {
    var docs = [document];
    var frames = document.querySelectorAll('iframe');
    Array.prototype.forEach.call(frames, function(frame) {
      try {
        if (frame.contentDocument && frame.contentDocument.documentElement) {
          docs.push(frame.contentDocument);
        }
      } catch (e) {}
    });
    return docs;
  }

  function ensureCss(doc) {
    if (!doc || !doc.head || doc.getElementById('A7_INLINE_CRM_AUDIO_PLAYER_CSS_LINK')) { return; }
    var link = doc.createElement('link');
    link.id = 'A7_INLINE_CRM_AUDIO_PLAYER_CSS_LINK';
    link.rel = 'stylesheet';
    link.href = cssHref;
    doc.head.appendChild(link);
  }

  function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) { return '0:00'; }
    seconds = Math.floor(seconds);
    var minutes = Math.floor(seconds / 60);
    var rest = seconds % 60;
    return minutes + ':' + (rest < 10 ? '0' : '') + rest;
  }

  function hideNativeFileRow(anchor) {
    var fileWrap = anchor.closest ? anchor.closest('.feed-com-file-wrap') : null;
    if (fileWrap) { fileWrap.classList.add('a7-audio-hidden'); }
    var filesBlock = anchor.closest ? anchor.closest('.feed-com-files') : null;
    if (filesBlock) {
      var title = filesBlock.querySelector('.feed-com-files-title');
      if (title) { title.classList.add('a7-audio-hidden'); }
    }
    return fileWrap;
  }

  function stopOtherPlayers(currentAudio) {
    getDocuments().forEach(function(doc) {
      var players = doc.querySelectorAll('.a7-voice-audio');
      Array.prototype.forEach.call(players, function(player) {
        if (player !== currentAudio) { player.pause(); }
      });
    });
  }

  function enhanceLink(doc, anchor) {
    if (!anchor || anchor.getAttribute('data-a7-inline-audio') === '1') { return; }
    var label = ((anchor.getAttribute('title') || '') + ' ' + (anchor.textContent || '')).toLowerCase();
    if (!audioNamePattern.test(label)) { return; }
    var href = anchor.href || anchor.getAttribute('href');
    if (!href) { return; }

    anchor.setAttribute('data-a7-inline-audio', '1');
    var fileWrap = hideNativeFileRow(anchor);
    var insertAfter = fileWrap || anchor;
    var parent = insertAfter.parentNode;
    if (!parent) { return; }

    var note = doc.createElement('div');
    note.className = 'a7-voice-note';

    var button = doc.createElement('button');
    button.type = 'button';
    button.className = 'a7-voice-play';
    button.setAttribute('aria-label', 'Play recording');

    var wave = doc.createElement('div');
    wave.className = 'a7-voice-wave';

    var time = doc.createElement('span');
    time.className = 'a7-voice-time';
    time.textContent = '0:00';

    var audio = doc.createElement('audio');
    audio.className = 'a7-voice-audio';
    audio.preload = 'metadata';
    audio.src = href;

    note.appendChild(button);
    note.appendChild(wave);
    note.appendChild(time);
    note.appendChild(audio);
    parent.insertBefore(note, insertAfter.nextSibling);

    function update() {
      var duration = audio.duration || 0;
      var current = audio.currentTime || 0;
      var remaining = duration ? Math.max(0, duration - current) : 0;
      time.textContent = duration ? '-' + formatTime(remaining) : '0:00';
      var progress = duration ? Math.max(0, Math.min(100, (current / duration) * 100)) : 0;
      wave.style.setProperty('--a7-progress', progress + '%');
    }

    button.addEventListener('click', function() {
      if (audio.paused) {
        stopOtherPlayers(audio);
        audio.play().catch(function(){});
      } else {
        audio.pause();
      }
    });

    wave.addEventListener('click', function(event) {
      if (!audio.duration) { return; }
      var rect = wave.getBoundingClientRect();
      audio.currentTime = ((event.clientX - rect.left) / rect.width) * audio.duration;
      update();
    });

    audio.addEventListener('loadedmetadata', update);
    audio.addEventListener('timeupdate', update);
    audio.addEventListener('play', function(){ note.classList.add('is-playing'); });
    audio.addEventListener('pause', function(){ note.classList.remove('is-playing'); });
    audio.addEventListener('ended', function(){ note.classList.remove('is-playing'); update(); });
  }

  function enhanceDocument(doc) {
    if (!doc || !doc.querySelectorAll) { return; }
    ensureCss(doc);
    var links = doc.querySelectorAll('a.feed-com-file-name');
    Array.prototype.forEach.call(links, function(anchor) { enhanceLink(doc, anchor); });
  }

  function enhanceAll() {
    getDocuments().forEach(enhanceDocument);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhanceAll);
  } else {
    enhanceAll();
  }
  var observer = new MutationObserver(enhanceAll);
  observer.observe(document.documentElement, {childList:true, subtree:true});
  setInterval(enhanceAll, 1500);
})();