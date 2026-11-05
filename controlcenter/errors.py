"""Коды ошибок — те же, что в руководстве ControlCenter (UDP-коды переосмыслены под HTTP)."""

ERROR_TEXT = {
    404: "C-E Connection error: 404 - Server not found (Node-RED недоступен)",
    471: 'M-E Message error: 471 - No variable declared "robot_name"',
    472: "M-E Message error: 472 - One or more variables are not declared",
    473: 'M-E Message error: 473 - Incorrect text value entered for "Start" or "Parking"',
    474: "M-E Message error: 474 - N variable is not increment for select device",
    481: "P-E Position error: 481 - The number position was not found",
    482: "T-E Tool error: 482 - The value for the working tool is incorrect",
    570: "N-E Name error: 570 - The device name wasn't found in the list of the selected command",
    571: "V-E Variable error: 571 - Variable has wrong type",
    581: "E-E Equipment error: 581 - Error sending HTTP request to the manipulator",
    582: "E-E Equipment error: 582 - Error sending HTTP request to other devices",
    583: "E-E Equipment error: 583 - Device is offline (no answer to polling)",
    584: "E-E Equipment error: 584 - Device answered with an HTTP error",
    585: "E-E Equipment error: 585 - Command is not supported by the device API",
    590: "S-E Settings error: 590 - Invalid settings, nothing was saved",
    591: 'R-E Read error: 591 - Error reading files in the directory "config"',
    592: 'R-E Read error: 592 - Error reading files in the directory "points"',
    593: 'W-E Write error: 593 - Error writing files in the directory "logs"',
    601: "U-E Feedback error: 601 - Error parsing feedback from equipment",
}


class CCError(Exception):
    def __init__(self, code: int, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{ERROR_TEXT.get(code, code)}{': ' + detail if detail else ''}")
