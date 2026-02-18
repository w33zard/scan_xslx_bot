# Деплой scan_xslx_bot на сервер

## Сервер: root@194.67.88.36

### 1. Создать репозиторий на GitHub

1. Создайте репозиторий **scan_xslx_bot** на https://github.com/new
2. Залейте код (см. ниже)

### 2. Первоначальная настройка сервера

```bash
# Подключиться к серверу
ssh root@194.67.88.36

# Вариант A: вручную
apt-get update && apt-get install -y docker.io docker-compose-v2 git
mkdir -p /root/scan_xslx_bot
cd /root/scan_xslx_bot
git clone https://github.com/YOUR_USERNAME/scan_xslx_bot.git .
cp .env.example .env
nano .env   # вписать TELEGRAM_BOT_TOKEN
docker compose up -d --build

# Вариант B: через скрипт (подставьте URL своего репо)
curl -sL https://raw.githubusercontent.com/YOUR_USERNAME/scan_xslx_bot/main/scripts/deploy.sh | bash -s https://github.com/YOUR_USERNAME/scan_xslx_bot.git
```

### 3. GitHub Actions — автообновление

Чтобы при каждом `git push` бот обновлялся на сервере:

1. **Создайте SSH-ключ для деплоя** (на своей машине):
   ```bash
   ssh-keygen -t ed25519 -C "deploy" -f deploy_key -N ""
   ```

2. **Добавьте публичный ключ на сервер**:
   ```bash
   ssh-copy-id -i deploy_key.pub root@194.67.88.36
   ```

3. **Добавьте секреты в GitHub** (Settings → Secrets and variables → Actions):
   - `SERVER_HOST` = `194.67.88.36`
   - `SERVER_USER` = `root`
   - `SSH_PRIVATE_KEY` = содержимое файла `deploy_key` (приватный ключ)

4. После `git push` в ветку `main` запустится деплой.

### 4. Заливка кода в GitHub

```bash
cd d:\scan_xslx_bot

git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/scan_xslx_bot.git
git push -u origin main
```

Замените `YOUR_USERNAME` на свой логин GitHub.

### 5. Проверка

```bash
ssh root@194.67.88.36
cd /root/scan_xslx_bot
docker compose ps
docker compose logs -f bot
```
