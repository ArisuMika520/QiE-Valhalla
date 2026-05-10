(() => {
  const want = ["skey", "p_skey", "p_uin", "uin"];
  const parsed = Object.fromEntries(
    document.cookie
      .split(/;\s*/)
      .filter(Boolean)
      .map((item) => {
        const index = item.indexOf("=");
        return [item.slice(0, index), item.slice(index + 1)];
      })
  );
  const parts = want.filter((name) => parsed[name]).map((name) => `${name}=${parsed[name]}`);
  const missing = want.filter((name) => !parsed[name]);
  const envLine = `QQ_VALHALLA_COOKIE="${parts.join("; ")}"`;
  const masked = parts
    .map((item) => item.replace(/=.{4,}/, "=<已复制，已隐藏>"))
    .join("; ");
  const done = () => {
    console.log(`已复制到剪贴板：QQ_VALHALLA_COOKIE="${masked}"`);
    if (missing.length) console.warn(`未找到：${missing.join(", ")}`);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(envLine).then(done);
  } else {
    console.log(envLine);
    console.warn("当前浏览器不允许自动复制，请手动复制上一行。");
  }
})();
