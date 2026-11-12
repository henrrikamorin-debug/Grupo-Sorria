# BI Contas a Pagar — Worker Cloudflare (`painel-financeiro-sorria`)

Código-fonte do Worker publicado, reconstruído em 12/11/2026 a partir do mapa de fontes do próprio deploy
(versão de 11/11/2026 15:11 UTC, lida pela API do Cloudflare, somente leitura). O código original fica no
computador do escritório (`painel-financeiro/cloudflare`); `bi.js`, `painel.js` e `xlsx.js` são os motores de
cálculo de `web/js/motor/`, que o Worker importa.

Nada aqui é publicado automaticamente. Para publicar, a mudança tem de ser levada ao projeto do escritório e
implantada por lá (`wrangler deploy`), depois de revisada.

Testes: `node --test tests/`
