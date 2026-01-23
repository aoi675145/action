name: X10Hosting Keep Alive

on:
  schedule:
    - cron: '0 */1 * * *'
  workflow_dispatch:

jobs:
  keep-alive:
    runs-on: ubuntu-latest
    
    steps:
      - name: Setup
        run: |
          npm init -y
          npm install node-fetch@2 tweetnacl tweetnacl-util
          
          wget -q https://github.com/apernet/hysteria/releases/latest/download/hysteria-linux-amd64 -O hysteria
          chmod +x hysteria

      - name: 启动代理
        env:
          HY2_URL: ${{ secrets.HY2_URL_JP }}
        run: |
          # 解析 URL 并创建配置
          URL_BODY="${HY2_URL#hysteria2://}"
          URL_BODY="${URL_BODY%%#*}"
          PASSWORD="${URL_BODY%%@*}"
          SERVER_PART="${URL_BODY#*@}"
          SERVER="${SERVER_PART%%\?*}"
          PARAMS="${SERVER_PART#*\?}"
          
          get_param() { echo "$PARAMS" | tr '&' '\n' | grep "^$1=" | cut -d'=' -f2; }
          SNI=$(get_param "sni")
          INSECURE=$(get_param "insecure")
          [ -z "$SNI" ] && SNI="${SERVER%%:*}"
          [ "$INSECURE" = "1" ] && INSECURE="true" || INSECURE="false"
          
          cat > hy2-config.yaml << EOF
          server: ${SERVER}
          auth: ${PASSWORD}
          tls:
            sni: ${SNI}
            insecure: ${INSECURE}
          socks5:
            listen: 127.0.0.1:1080
          http:
            listen: 127.0.0.1:8080
          EOF
          
          ./hysteria client -c hy2-config.yaml &
          sleep 3
          echo "代理IP: $(curl -s --proxy socks5h://127.0.0.1:1080 https://api.ipify.org)"

      - name: 刷新 Cookie
        env:
          X10_SESSION: ${{ secrets.X10_SESSION }}
          X10_XSRF: ${{ secrets.X10_XSRF }}
          REPO_TOKEN: ${{ secrets.REPO_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
        run: |
          node << 'EOF'
          const fetch = require('node-fetch');
          const nacl = require('tweetnacl');
          const { decodeBase64, encodeBase64 } = require('tweetnacl-util');
          const { SocksProxyAgent } = require('socks-proxy-agent');

          // 需要安装 socks-proxy-agent
          // 或者使用 http 代理

          const agent = new (require('https-proxy-agent').HttpsProxyAgent)('http://127.0.0.1:8080');

          async function updateSecret(name, value) {
            const repo = process.env.GITHUB_REPO;
            const token = process.env.REPO_TOKEN;
            
            // 获取公钥
            const keyRes = await fetch(`https://api.github.com/repos/${repo}/actions/secrets/public-key`, {
              headers: {
                'Authorization': `Bearer ${token}`,
                'Accept': 'application/vnd.github+json'
              }
            });
            const { key, key_id } = await keyRes.json();
            
            // 加密
            const keyBytes = decodeBase64(key);
            const valueBytes = new TextEncoder().encode(value);
            const encrypted = nacl.box.seal(valueBytes, keyBytes);
            const encryptedB64 = encodeBase64(encrypted);
            
            // 更新
            await fetch(`https://api.github.com/repos/${repo}/actions/secrets/${name}`, {
              method: 'PUT',
              headers: {
                'Authorization': `Bearer ${token}`,
                'Accept': 'application/vnd.github+json',
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({ encrypted_value: encryptedB64, key_id })
            });
            
            console.log(`✅ ${name} 已更新`);
          }

          (async () => {
            const session = process.env.X10_SESSION;
            const xsrf = process.env.X10_XSRF;
            
            console.log('📍 访问面板...');
            
            const res = await fetch('https://x10hosting.com/panel/services/175344', {
              agent,
              headers: {
                'Cookie': `XSRF-TOKEN=${xsrf}; x10hosting_session=${session}`,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/143.0.0.0'
              },
              redirect: 'manual'
            });
            
            // 检查响应
            const location = res.headers.get('location');
            if (location && location.includes('login')) {
              console.log('❌ Cookie 已过期');
              process.exit(1);
            }
            
            console.log(`✅ 状态: ${res.status}`);
            
            // 获取新 Cookie
            const setCookies = res.headers.raw()['set-cookie'] || [];
            let newSession = session;
            let newXsrf = xsrf;
            
            for (const cookie of setCookies) {
              if (cookie.startsWith('x10hosting_session=')) {
                newSession = cookie.split('=')[1].split(';')[0];
              }
              if (cookie.startsWith('XSRF-TOKEN=')) {
                newXsrf = cookie.split('=')[1].split(';')[0];
              }
            }
            
            // 更新 Secrets
            if (newSession !== session) await updateSecret('X10_SESSION', newSession);
            if (newXsrf !== xsrf) await updateSecret('X10_XSRF', newXsrf);
            
            console.log('🎉 完成!');
          })();
          EOF
