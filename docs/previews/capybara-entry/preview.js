'use strict';
document.querySelectorAll('[data-preview]').forEach(function (button) {
  button.addEventListener('click', function () {
    var action = button.dataset.preview;
    document.getElementById('dialog-title').textContent = action + ' · 预览';
    document.getElementById('dialog-copy').textContent = action.includes('下载')
      ? '这里只展示下载入口的交互。安装包尚未接入，本次没有发布或下载安装任何软件。'
      : '这里只展示进入应用后的衔接。正式实施时接入现有账号系统，本次不提交任何账号信息。';
    document.getElementById('preview-dialog').showModal();
  });
});
