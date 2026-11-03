<main class="capy-entry-gate">
  @if($account_entry ?? false)
    <nav class="capy-account-entry" aria-label="账号入口">
      <a href="#/login">账号登录</a>
      <a class="capy-entry-register" href="#/register">注册账号</a>
    </nav>
  @else
    <a href="#/login">点击进入官网</a>
  @endif
</main>
