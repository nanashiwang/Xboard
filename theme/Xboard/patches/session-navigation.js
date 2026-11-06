function VN(router) {
  router.beforeEach(() => window.$loadingBar?.start());
  router.afterEach(() => setTimeout(() => window.$loadingBar?.finish(), 200));
  router.onError(() => window.$loadingBar?.error());
  const user = BN(), permission = $N();
  router.beforeEach(async (to, from, next) => {
    if (!dd().value) return next(UN.includes(to.path) ? undefined : {path: "/login"});
    if (to.path === "/login") return next({path: to.query.redirect?.toString() ?? "/dashboard"});
    if (user.userUUID) return next();
    try {
      await Promise.all([_N().getConfig(), user.getUserInfo()]);
    } catch (error) {
      const expired = error?.code === 401 || (error?.code === 403 && error?.message === "未登录或登陆已过期");
      if (expired) pd();
      window.$message.error(expired ? "登录已过期，请重新登录" : "暂时无法获取账号信息，登录状态已保留，请刷新重试");
      return next(expired ? {path: "/login"} : false);
    }
    permission.generateRoutes(user.role).forEach(route => {
      if (route.name && !router.hasRoute(route.name)) router.addRoute(route);
    });
    router.addRoute(bs);
    next({...to, replace: true});
  });
  router.afterEach(to => {
    document.title = to.meta?.title ? `${to.meta.title} | ${Cs}` : Cs;
  });
}
