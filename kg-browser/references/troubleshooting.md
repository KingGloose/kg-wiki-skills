# Kimi WebBridge 排查

## 守护进程未运行

`kimi-bridge.mjs` 遇到 `ECONNREFUSED` 会自动执行：

```bash
~/.kimi-webbridge/bin/kimi-webbridge start
```

仍无法连接时打开 [Kimi WebBridge 中文帮助](https://www.kimi.com/zh-cn/features/webbridge)。不要自动执行 `stop` / `restart` / `uninstall`，这些会中断其他正在使用浏览器的任务。

## `no extension connected`

守护进程正常，但 Chrome 扩展未连接。请用户检查 Kimi WebBridge 扩展是否已启用，并在扩展界面完成连接。不要尝试导出 cookie 或改用隐藏浏览器。

## 扩展版本过旧

返回 `Please update the Kimi WebBridge extension` 时，让用户按帮助页更新扩展。不要由脚本自动升级。

## 页面内容不完整

1. 用 `snapshot` 检查登录页、加载状态和折叠按钮。
2. 页面变化后重新 snapshot；旧 `@e` 引用可能已失效。
3. 长页用 `evaluate` 滚动后分段读取。
4. 跨域 iframe 不能直接操作时，先取 iframe URL，再导航到该 URL。
5. 某些站点要求真实用户输入，普通 click/fill 无效时让用户手动完成。

## 历史搜索失败

- macOS 默认读 `~/Library/Application Support/Google/Chrome`。
- Linux 默认读 `~/.config/google-chrome` / `chromium` / Edge。
- Windows 默认读 `%LOCALAPPDATA%/Google/Chrome/User Data`。
- WSL 会额外遍历 `/mnt/c/Users/*/AppData/Local/Google/Chrome/User Data`。

自动探测不对时传 `--chrome-home <path>`。
