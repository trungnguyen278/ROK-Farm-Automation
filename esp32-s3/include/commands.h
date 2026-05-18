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

#define RSP_ACK  "ACK"
#define RSP_NACK "NACK"
#define RSP_PONG "PONG"

#define ERR_UNKNOWN_CMD    1
#define ERR_INVALID_PARAMS 2
#define ERR_BUSY           3

#define STEP_INTERVAL_MS   5
#define MAX_PARAMS         8
#define MAX_PARAM_LEN      16
#define MAX_LINE_LEN       128

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
