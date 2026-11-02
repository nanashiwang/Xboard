<style>
  .capy-panel-loading { display:none; }
  html[data-xboard-page="panel"] .capy-panel-loading:not([hidden]) { min-height:70vh; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:16px; padding:24px; box-sizing:border-box; color:#475569; background:#fff; font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; text-align:center; }
  .capy-panel-loading p { margin:0; }
  .capy-panel-loading nav { display:flex; gap:20px; }
  .capy-panel-loading a { color:#087bff; text-underline-offset:4px; }
  .capy-panel-spinner { width:26px; height:26px; border:3px solid #dbeafe; border-top-color:#087bff; border-radius:50%; animation:capy-panel-spin .8s linear infinite; }
  @keyframes capy-panel-spin { to { transform:rotate(360deg); } }
  @media(prefers-reduced-motion:reduce) { .capy-panel-spinner { animation:none; } }
</style>
