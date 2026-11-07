const http = require("http");

function registrationRequest(path, method, body) {
    return new Promise(resolve => {
        const payload = body ? JSON.stringify(body) : "";
        const url = new URL(path, process.env.REGISTRATION_URL);
        const request = http.request(url, {
            method,
            headers: payload ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(payload)
            } : {},
            timeout: 3000
        }, response => {
            let data = "";
            response.on("data", chunk => data += chunk);
            response.on("end", () => {
                if (response.statusCode !== 200) return resolve(null);
                try {
                    resolve(JSON.parse(data));
                } catch {
                    resolve(null);
                }
            });
        });
        request.on("timeout", () => {
            request.destroy();
            resolve(null);
        });
        request.on("error", () => resolve(null));
        request.end(payload);
    });
}

module.exports = {
    flowFile: "flows.json",
    flowFilePretty: true,
    credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET || false,
    adminAuth: {
        type: "credentials",
        users: username => registrationRequest(`/users/${encodeURIComponent(username)}`, "GET"),
        authenticate: (username, password) => registrationRequest("/auth", "POST", {username, password})
    },
    mysqlReconnectTime: 30000,
    logging: {
        console: {
            level: "info",
            metrics: false,
            audit: false
        }
    }
};
