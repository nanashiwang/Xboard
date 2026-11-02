#!/usr/bin/env python3
"""Reproducible patch of the vendored theme; refuse unknown upstream structures."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
p = ROOT/'theme/Xboard/assets/umi.js'
s = p.read_text()
a = s.index('const YY=zn(') + len('const YY=zn(')
b = s.index('),QY={ref:"turnstile"}', a)
s = s[:a] + (ROOT/'theme/Xboard/patches/turnstile-component.js').read_text().strip() + s[b:]
old = 'function _(){f.value="",T()}'
new = 'function _(){f.value="",m.value="",y.value="",h.value=!1,window.$message.error("人机验证未完成或已过期，请检查网络后重新点击发送或注册。")}'
assert s.count(old) == 1 or s.count(new) == 1, 'Unexpected auth failure handler'
s = s.replace(old, new)
p.write_text(s)
