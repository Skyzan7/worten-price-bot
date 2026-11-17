# 🤖 Bot de falhas de preço Worten → Telegram

Faz scan às páginas da Worten de **30 em 30 minutos**, guarda o histórico de
preços e envia alerta para o Telegram quando um preço parece um erro.

Tudo gratuito: a Worten não tem API pública, por isso o bot lê as páginas
públicas (dados estruturados JSON-LD / JSON embebido) e usa a **API do Telegram**,
que é gratuita.

## Como deteta falhas

| Regra | Exemplo |
|---|---|
| Queda ≥ 40 % face à mediana do histórico do produto | TV que esteve sempre a 899 € aparece a 499 € |
| Desconto ≥ 60 % face ao preço riscado da Worten | “de 979 € por 299 €” |
| Preço absurdo (< 10 € num produto ≥ 100 €) | iPhone a 9,99 € |

Não repete o mesmo alerta (produto + preço) durante 24 h. Tudo ajustável em `config.yaml`.

## 1. Criar o bot no Telegram (2 min)

1. Fala com **@BotFather** → `/newbot` → copia o *token*.
2. Fala com **@userinfobot** → copia o teu *ID*.
3. Envia uma mensagem qualquer ao teu bot novo (para ele te poder escrever).

## 2. Opção A — correr no teu PC / Raspberry Pi / VPS

```bash
pip install -r requirements.txt
cp .env.example .env      # preenche TELEGRAM_TOKEN e TELEGRAM_CHAT_ID
python bot.py
```

Comandos no Telegram:

- `/scan` — faz scan agora
- `/status` — produtos seguidos, alertas, próximo scan
- `/list` — páginas vigiadas
- `/add <url>` — vigiar mais uma página (pesquisa, categoria, promoções)
- `/remove <url>` — deixar de vigiar
- `/regras` — limites atuais

Só responde ao teu `TELEGRAM_CHAT_ID`.

**Servidor grátis 24/7:** Oracle Cloud *Always Free* ou um Raspberry Pi em casa.

## 2. Opção B — GitHub Actions (sem servidor, grátis)

1. Cria um repositório **privado** no GitHub e envia esta pasta.
2. *Settings → Secrets and variables → Actions* → cria `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`.
3. Pronto — `.github/workflows/scan.yml` corre de 30 em 30 min e guarda o histórico em cache.
   (Nesta opção não há comandos interativos; as URLs editam-se no `config.yaml`.)

## Primeiras horas

- A regra do histórico só começa depois de 3 leituras por produto (~1h30).
  Até lá só funcionam as regras do preço riscado e do preço absurdo.
- Se um scan devolver 0 produtos, o HTML fica guardado em `data/debug/`.
  Isso indica que a Worten mudou o site ou bloqueou o pedido — os
  ficheiros ajudam a ajustar o `scraper.py`.

## Testes

```bash
pip install pytest && pytest -q
```

## Avisos

- Usa intervalos razoáveis (30 min e poucas páginas) para não sobrecarregar o site.
- Em Portugal, um preço **manifestamente errado** pode não obrigar a loja a vender
  por esse valor — não é aconselhamento jurídico.
