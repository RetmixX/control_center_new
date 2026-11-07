#!/usr/bin/env node

const express = require('express');
const app = express();
const bodyParser = require('body-parser');
const PORT = 17381

console.log("First start------------------------------>");

app.listen(PORT, () => {
    const currentDate = new Date();
    console.log(currentDate.getDate() + " " + currentDate.toLocaleString('default', { month: 'short' }) + " " + ("0" + currentDate.getHours()).slice(-2) + ":" + ("0" + currentDate.getMinutes()).slice(-2) + ":" + ("0" + currentDate.getSeconds()).slice(-2) + ' - [info] IOT Control_center');

});