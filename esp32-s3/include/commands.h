#ifndef COMMANDS_H
#define COMMANDS_H

#define CMD_MOVE   "MOVE"
#define CMD_CLICK  "CLICK"
#define CMD_DCLICK "DCLICK"
#define CMD_MDOWN  "MDOWN"
#define CMD_MUP    "MUP"
#define CMD_SCROLL "SCROLL"
#define CMD_PING   "PING"
#define CMD_RESET  "RESET"
#define CMD_KEY    "KEY"
#define CMD_COMBO  "COMBO"
#define CMD_IDLE   "IDLE"
#define CMD_MOVETO "MOVETO"
#define CMD_DRAG   "DRAG"
#define CMD_PATH_CLR  "PCLR"
#define CMD_PATH_PT   "PPT"
#define CMD_PATH_GO   "PGO"
#define CMD_PATH_DRAG "PDRAG"
// USB link diagnostics / recovery. The native-USB PHY sometimes fails to
// re-attach after a flash, leaving the board reachable over UART but invisible
// to the host as an HID device -- which normally needs a physical replug.
#define CMD_USB_STAT  "USBST"
#define CMD_USB_REATT "USBRE"

#define RSP_ACK  "ACK"
#define RSP_NACK "NACK"
#define RSP_PONG "PONG"

#define ERR_UNKNOWN_CMD    1
#define ERR_INVALID_PARAMS 2
#define ERR_BUSY           3
#define ERR_PATH_FULL      4

#define MAX_PARAMS         8
#define MAX_PARAM_LEN      16
#define MAX_LINE_LEN       128

#define MAX_PATH_POINTS    128

// Sub-step cadence (ms) for interpolating between path waypoints. Matches a
// real ~125 Hz HID report rate so the cursor advances in small continuous
// deltas instead of teleporting between waypoints.
#define PATH_STEP_MS       8

struct PathPoint {
    int16_t x;
    int16_t y;
    uint8_t delay_ms;   // travel time from the previous waypoint to this one
};

#define BTN_LEFT   'L'
#define BTN_RIGHT  'R'
#define BTN_MIDDLE 'M'

struct ParsedCommand {
    int cmd_id;
    char command[16];
    char params[MAX_PARAMS][MAX_PARAM_LEN];
    int param_count;
    bool valid;
};

#endif
