const fs = require("fs");
const express = require("express");
const bcrypt = require("bcryptjs");
const mysql = require("mysql2/promise");

const accountFile = "/config/accounts.json";
const loginPattern = /^[a-z][a-z0-9_]{2,31}$/;
let accounts = fs.existsSync(accountFile) ? JSON.parse(fs.readFileSync(accountFile, "utf8")) : [];
let queue = Promise.resolve();

const page = `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#8f0000">
<title>Регистрация — IoT Control Center</title>
<style>
:root{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:#333;background:#e9e9e9;font-synthesis:none}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:32px 24px;background:#e9e9e9}
.shell{position:relative;width:min(960px,100%);display:grid;grid-template-columns:1fr 1fr;border:1px solid #c6c6c6;border-radius:5px;overflow:hidden;box-shadow:0 8px 28px rgba(0,0,0,.16);background:#fff}
.topbar{grid-column:1/-1;min-height:62px;padding:12px 22px;display:flex;align-items:center;justify-content:space-between;gap:20px;background:#8f0000;color:#fff;border-bottom:1px solid #720000}.brand{display:flex;align-items:center;gap:11px;font-size:17px;font-weight:700;letter-spacing:.01em}.brand svg{width:34px;height:34px}.brand span{font-size:13px;font-weight:400;color:#edc5c5}.topbar-label{font-size:12px;color:#edc5c5}
.hero{position:relative;padding:38px 40px;color:#fff;background:#2c2c2c;display:flex;flex-direction:column;border-right:1px solid #222}.hero-content{margin:auto 0;padding:44px 0 38px}.eyebrow{margin:0 0 14px;color:#e3a0a0;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}.hero h1{margin:0;font-size:38px;line-height:1.18;letter-spacing:-.025em;font-weight:500}.intro{margin:18px 0 0;color:#c9c9c9;font-size:14px;line-height:1.7}
.steps{display:grid;gap:15px;margin:0;padding:0;list-style:none}.steps li{display:flex;align-items:center;gap:12px;color:#ddd;font-size:12px;line-height:1.45}.number{display:grid;place-items:center;flex:0 0 29px;height:29px;border:1px solid #8f4b4b;border-radius:3px;color:#efb3b3;font-size:10px;font-weight:700;background:#382828}
.panel{padding:40px 42px;background:#fff}.panel-heading{margin-bottom:26px}.kicker{margin:0 0 8px;color:#8f0000;font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}.panel h2{margin:0;color:#333;font-size:26px;letter-spacing:-.02em;font-weight:500}.subtitle{margin:9px 0 0;color:#777;font-size:13px;line-height:1.55}
.field{margin-top:20px}.field label{display:block;margin:0 0 7px;color:#444;font-size:12px;font-weight:700}.input-wrap{position:relative}.input-wrap input{width:100%;height:43px;border:1px solid #ccc;border-radius:3px;background:#fff;padding:0 12px;color:#333;font-size:14px;outline:none;transition:border-color .15s,box-shadow .15s}.input-wrap input:hover{border-color:#aaa}.input-wrap input:focus{border-color:#8f0000;box-shadow:0 0 0 2px rgba(143,0,0,.1)}.input-wrap input:invalid:not(:placeholder-shown){border-color:#b44747}.password-input{padding-right:76px!important}.toggle{position:absolute;right:5px;top:5px;height:33px;padding:0 9px;border:0;border-radius:2px;background:transparent;color:#8f0000;font-size:11px;font-weight:700;cursor:pointer}.toggle:hover{background:#f5e8e8}
.hint{display:block;margin-top:7px;color:#888;font-size:10px;line-height:1.45}.submit{width:100%;height:44px;margin-top:25px;border:1px solid #760000;border-radius:3px;background:#8f0000;color:#fff;font-size:13px;font-weight:700;cursor:pointer;transition:background .15s}.submit:hover:not(:disabled){background:#a20000}.submit:active:not(:disabled){background:#760000}.submit:disabled{cursor:wait;opacity:.7}.button-content{display:flex;align-items:center;justify-content:center;gap:9px}.arrow{font-size:17px;font-weight:400}.spinner{display:none;width:15px;height:15px;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite}.loading .spinner{display:block}.loading .arrow{display:none}@keyframes spin{to{transform:rotate(360deg)}}
.notice{display:flex;gap:10px;margin-top:20px;padding:12px;border:1px solid #e2e2e2;border-radius:3px;background:#f6f6f6;color:#777;font-size:10px;line-height:1.55}.notice svg{flex:0 0 16px;color:#8f0000;margin-top:1px}.error{margin-top:16px;padding:12px;border:1px solid #d9aaaa;border-radius:3px;background:#fff1f1;color:#8f0000;font-size:12px;line-height:1.5}.footer{margin-top:23px;text-align:center;color:#999;font-size:10px}
.success{text-align:center;padding:8px 0}.success-icon{display:grid;place-items:center;width:58px;height:58px;margin:0 auto 18px;border-radius:4px;background:#f5e4e4;color:#8f0000}.success-icon svg{width:30px;height:30px}.success h2{font-size:27px}.success .subtitle{margin-bottom:22px}.credentials{padding:8px 18px;border:1px solid #d5d5d5;border-radius:4px;background:#f7f7f7;text-align:left}.credential{display:flex;justify-content:space-between;align-items:center;gap:18px;padding:15px 0;border-bottom:1px solid #ddd;font-size:14px}.credential:last-child{border-bottom:0}.credential span{color:#666}.credential strong{color:#222;font-family:Consolas,monospace;font-size:16px;font-weight:700;overflow-wrap:anywhere;text-align:right}.same-password{margin:17px 0 0;color:#666;font-size:13px;line-height:1.55}.nodered-button{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;min-height:48px;margin-top:24px;border:1px solid #760000;border-radius:3px;background:#8f0000;color:#fff;font-size:15px;font-weight:700;text-decoration:none;transition:background .15s}.nodered-button:hover{background:#a20000}.nodered-button:active{background:#760000}
[hidden]{display:none!important}@media(max-width:760px){body{padding:18px 14px}.shell{grid-template-columns:1fr}.hero{padding:26px 28px;border-right:0}.hero-content{padding:26px 0}.hero h1{font-size:30px}.intro{margin-top:12px}.steps{grid-template-columns:1fr 1fr;gap:10px}.steps li{font-size:10px}.panel{padding:30px 28px}.topbar{padding:11px 16px}}@media(max-width:500px){.topbar-label,.steps{display:none}.brand{font-size:15px}.brand span{font-size:11px}.hero-content{padding:14px 0 4px}.hero h1{font-size:27px}.panel{padding:26px 22px}.credential{align-items:flex-start;flex-direction:column;gap:4px}.credential strong{text-align:left}}
</style>
</head>
<body>
<main class="shell">
<div class="topbar"><div class="brand"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect width="40" height="40" rx="4" fill="#fff"/><path d="M10 12h20M10 20h13M10 28h20" stroke="#8F0000" stroke-width="3" stroke-linecap="square"/><rect x="26" y="17" width="5" height="6" fill="#8F0000"/></svg><div>Node-RED <span>/ IoT Control Center</span></div></div><div class="topbar-label">Регистрация участника</div></div>
<section class="hero">
<div class="hero-content"><p class="eyebrow">Единая точка входа</p><h1>Ваша рабочая зона.<br>Ваши данные.</h1><p class="intro">Создайте аккаунт, чтобы работать с флоу Node-RED и собственной базой данных MySQL.</p></div>
<ul class="steps"><li><span class="number">01</span><span>Придумайте логин и надёжный пароль</span></li><li><span class="number">02</span><span>Получите личную базу данных автоматически</span></li><li><span class="number">03</span><span>Войдите в Node-RED без ожидания</span></li></ul>
</section>
<section class="panel">
<div id="registration">
<div class="panel-heading"><p class="kicker">Новый участник</p><h2>Создайте аккаунт</h2><p class="subtitle">Одна регистрация — доступ к Node-RED и MySQL.</p></div>
<form id="form">
<div class="field"><label for="username">Логин</label><div class="input-wrap"><input id="username" name="username" placeholder="например, participant_1" pattern="[a-z][a-z0-9_]{2,31}" autocomplete="username" required></div><small class="hint">3–32 символа: строчные латинские буквы, цифры и _</small></div>
<div class="field"><label for="password">Пароль</label><div class="input-wrap"><input class="password-input" id="password" name="password" type="password" placeholder="Введите пароль" maxlength="128" autocomplete="new-password" required><button class="toggle" id="toggle" type="button" aria-label="Показать пароль">Показать</button></div><small class="hint">Этот же пароль будет использоваться для вашей базы MySQL</small></div>
<button class="submit" id="submit" type="submit"><span class="button-content"><span class="spinner" aria-hidden="true"></span><span id="submit-label">Создать аккаунт</span><span class="arrow" aria-hidden="true">→</span></span></button>
<div class="error" id="error" role="alert" hidden></div>
</form>
<div class="notice"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3 4 6v5c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V6l-8-3Z" stroke="currentColor" stroke-width="1.8"/><path d="m9 12 2 2 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Для каждого участника создаётся отдельная база. Доступ к чужим базам не выдаётся.</span></div>
</div>
<div class="success" id="success" role="status" hidden>
<div class="success-icon"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4 4L19 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
<p class="kicker">Готово</p><h2>Аккаунт создан</h2><p class="subtitle">Теперь вы можете войти в Node-RED.<br>Параметры вашей базы MySQL:</p>
<div class="credentials"><div class="credential"><span>Хост</span><strong id="db-host"></strong></div><div class="credential"><span>Порт</span><strong id="db-port"></strong></div><div class="credential"><span>База данных</span><strong id="db-name"></strong></div><div class="credential"><span>Пользователь</span><strong id="db-user"></strong></div></div>
<p class="same-password">Для подключения к MySQL используйте пароль, указанный при регистрации.</p>
<a class="nodered-button" id="nodered-link" href="#">Перейти в Node-RED <span class="arrow" aria-hidden="true">→</span></a>
</div>
<div class="footer">IoT Control Center · Самостоятельная регистрация</div>
</section>
</main>
<script>
const form=document.getElementById('form');
const password=document.getElementById('password');
const toggle=document.getElementById('toggle');
const submit=document.getElementById('submit');
const submitLabel=document.getElementById('submit-label');
const errorBox=document.getElementById('error');
const nodeRedPort=${JSON.stringify(process.env.NODE_RED_PORT || "1880")};
const configuredNodeRedUrl=${JSON.stringify(process.env.NODE_RED_URL || "")};
toggle.addEventListener('click',()=>{const visible=password.type==='text';password.type=visible?'password':'text';toggle.textContent=visible?'Показать':'Скрыть';toggle.setAttribute('aria-label',visible?'Показать пароль':'Скрыть пароль');});
form.addEventListener('submit',async event=>{event.preventDefault();if(!form.reportValidity())return;errorBox.hidden=true;submit.disabled=true;submit.classList.add('loading');submitLabel.textContent='Создаём аккаунт...';
try{const response=await fetch('/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.username.value,password:form.password.value})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Не удалось создать аккаунт');
document.getElementById('db-host').textContent=data.mysql.host;document.getElementById('db-port').textContent=data.mysql.port;document.getElementById('db-name').textContent=data.mysql.database;document.getElementById('db-user').textContent=data.mysql.username;document.getElementById('nodered-link').href=configuredNodeRedUrl||location.protocol+'//'+location.hostname+':'+nodeRedPort;document.getElementById('registration').hidden=true;document.getElementById('success').hidden=false;
}catch(error){errorBox.textContent=error.message;errorBox.hidden=false;}finally{submit.disabled=false;submit.classList.remove('loading');submitLabel.textContent='Создать аккаунт';}});
</script>
</body>
</html>`;

function saveAccounts() {
    const temporary = `${accountFile}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(accounts, null, 2), {mode: 0o600});
    fs.renameSync(temporary, accountFile);
}

async function createAccount(body) {
    const username = String(body.username || "");
    const password = String(body.password || "");
    if (!loginPattern.test(username)) {
        throw Object.assign(new Error("Некорректный логин"), {status: 400});
    }
    if (!password || password.length > 128) {
        throw Object.assign(new Error("Пароль должен быть непустым и содержать не более 128 символов"), {status: 400});
    }
    if (accounts.some(account => account.username === username)) {
        throw Object.assign(new Error("Этот логин уже занят"), {status: 409});
    }

    const database = username;
    const connection = await mysql.createConnection({
        host: process.env.MYSQL_HOST,
        port: 3306,
        user: "root",
        password: process.env.MYSQL_ROOT_PASSWORD
    });
    try {
        await connection.query(`CREATE DATABASE \`${database}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`);
        await connection.query(`CREATE USER '${username}'@'%' IDENTIFIED BY ${connection.escape(password)}`);
        await connection.query(`GRANT ALL PRIVILEGES ON \`${database}\`.* TO '${username}'@'%'`);
    } finally {
        await connection.end();
    }

    accounts.push({
        username,
        password_hash: bcrypt.hashSync(password, 12),
        permissions: "*",
        database,
        mysql_user: username,
        created_at: new Date().toISOString()
    });
    saveAccounts();
    return {
        nodeRed: {username},
        mysql: {
            host: process.env.MYSQL_HOST,
            port: 3306,
            database,
            username
        },
        notice: "Для MySQL и Node-RED используются одинаковые логин и пароль."
    };
}

const app = express();
app.use(express.json({limit: "16kb"}));
app.get("/", (req, res) => res.type("html").send(page));
app.get("/health", (req, res) => res.json({status: "ok"}));
app.post("/register", async (req, res) => {
    const operation = queue.then(() => createAccount(req.body));
    queue = operation.catch(() => {});
    try {
        res.status(201).json(await operation);
    } catch (error) {
        console.error(error.message);
        res.status(error.status || 503).json({error: error.message});
    }
});
app.get("/users/:username", (req, res) => {
    const account = accounts.find(item => item.username === req.params.username);
    if (!account) return res.status(404).json({error: "Account not found"});
    res.json({username: account.username, permissions: account.permissions});
});
app.post("/auth", async (req, res) => {
    const account = accounts.find(item => item.username === req.body.username);
    if (!account || !await bcrypt.compare(String(req.body.password || ""), account.password_hash)) {
        return res.status(401).json({error: "Invalid credentials"});
    }
    res.json({username: account.username, permissions: account.permissions});
});

const server = app.listen(3000, "0.0.0.0", () => console.log("Registration service listening on :3000"));
process.on("SIGTERM", () => server.close(() => process.exit(0)));
