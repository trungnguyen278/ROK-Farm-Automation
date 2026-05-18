#include <Arduino.h>
#include "USB.h"
#include "USBHIDMouse.h"
#include "commands.h"

USBHIDMouse Mouse;

static char line_buf[MAX_LINE_LEN];
static int line_pos = 0;
static bool executing = false;

void send_ack(int cmd_id) {
    Serial.printf("<%d,%s>\n", cmd_id, RSP_ACK);
}

void send_nack(int cmd_id, int error_code) {
    Serial.printf("<%d,%s,%d>\n", cmd_id, RSP_NACK, error_code);
}

void send_pong() {
    Serial.printf("<0,%s>\n", RSP_PONG);
}

void rel_move(int16_t dx, int16_t dy) {
    while (dx != 0 || dy != 0) {
        int8_t sx = (int8_t)constrain(dx, -127, 127);
        int8_t sy = (int8_t)constrain(dy, -127, 127);
        Mouse.move(sx, sy, 0);
        dx -= sx;
        dy -= sy;
        if (dx != 0 || dy != 0) delay(1);
    }
}

// --- Parser ---

ParsedCommand parse_line(const char* line) {
    ParsedCommand cmd = {};
    cmd.valid = false;

    int len = strlen(line);
    if (len < 3 || line[0] != '<' || line[len - 1] != '>') return cmd;

    char buf[MAX_LINE_LEN];
    strncpy(buf, line + 1, len - 2);
    buf[len - 2] = '\0';

    char* token = strtok(buf, ",");
    if (!token) return cmd;
    cmd.cmd_id = atoi(token);

    token = strtok(NULL, ",");
    if (!token) return cmd;
    strncpy(cmd.command, token, sizeof(cmd.command) - 1);

    cmd.param_count = 0;
    while ((token = strtok(NULL, ",")) != NULL && cmd.param_count < MAX_PARAMS) {
        strncpy(cmd.params[cmd.param_count], token, MAX_PARAM_LEN - 1);
        cmd.param_count++;
    }

    cmd.valid = true;
    return cmd;
}

// --- Mouse button mapping ---

uint8_t map_button(char btn) {
    switch (btn) {
        case BTN_LEFT:   return MOUSE_LEFT;
        case BTN_RIGHT:  return MOUSE_RIGHT;
        case BTN_MIDDLE: return MOUSE_MIDDLE;
        default:         return MOUSE_LEFT;
    }
}

// --- Command handlers ---

void handle_move(const ParsedCommand& cmd) {
    if (cmd.param_count < 2) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    int dx_total = atoi(cmd.params[0]);
    int dy_total = atoi(cmd.params[1]);
    int duration_ms = (cmd.param_count >= 3) ? atoi(cmd.params[2]) : 0;

    if (duration_ms <= 0) {
        rel_move(dx_total, dy_total);
    } else {
        int steps = duration_ms / STEP_INTERVAL_MS;
        if (steps < 1) steps = 1;
        float dx = (float)dx_total / steps;
        float dy = (float)dy_total / steps;
        float accum_x = 0, accum_y = 0;
        for (int i = 0; i < steps; i++) {
            accum_x += dx;
            accum_y += dy;
            int mx = (int)accum_x;
            int my = (int)accum_y;
            if (mx != 0 || my != 0) {
                rel_move(mx, my);
            }
            accum_x -= mx;
            accum_y -= my;
            delay(STEP_INTERVAL_MS);
        }
    }
    send_ack(cmd.cmd_id);
}

void handle_click(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    uint8_t button = map_button(cmd.params[0][0]);
    int hold_ms = (cmd.param_count >= 2) ? atoi(cmd.params[1]) : 50;

    Mouse.press(button);
    delay(hold_ms);
    Mouse.release(button);
    send_ack(cmd.cmd_id);
}

void handle_dclick(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    uint8_t button = map_button(cmd.params[0][0]);
    int gap_ms = (cmd.param_count >= 2) ? atoi(cmd.params[1]) : 80;

    Mouse.press(button);
    delay(50);
    Mouse.release(button);
    delay(gap_ms);
    Mouse.press(button);
    delay(50);
    Mouse.release(button);
    send_ack(cmd.cmd_id);
}

void handle_mdown(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    uint8_t button = map_button(cmd.params[0][0]);
    Mouse.press(button);
    send_ack(cmd.cmd_id);
}

void handle_mup(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    uint8_t button = map_button(cmd.params[0][0]);
    Mouse.release(button);
    send_ack(cmd.cmd_id);
}

void handle_scroll(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    int amount = atoi(cmd.params[0]);
    while (amount != 0) {
        int8_t s = (int8_t)constrain(amount, -127, 127);
        Mouse.move(0, 0, s);
        amount -= s;
        if (amount != 0) delay(1);
    }
    send_ack(cmd.cmd_id);
}

void handle_reset(const ParsedCommand& cmd) {
    Mouse.release(MOUSE_LEFT);
    Mouse.release(MOUSE_RIGHT);
    Mouse.release(MOUSE_MIDDLE);
    send_ack(cmd.cmd_id);
}

// --- Dispatcher ---

void execute_command(const ParsedCommand& cmd) {
    if (strcmp(cmd.command, CMD_PING) == 0)       { send_pong(); return; }
    if (strcmp(cmd.command, CMD_RESET) == 0)      { handle_reset(cmd); return; }

    if (executing) { send_nack(cmd.cmd_id, ERR_BUSY); return; }
    executing = true;

    if      (strcmp(cmd.command, CMD_MOVE) == 0)   handle_move(cmd);
    else if (strcmp(cmd.command, CMD_CLICK) == 0)  handle_click(cmd);
    else if (strcmp(cmd.command, CMD_DCLICK) == 0) handle_dclick(cmd);
    else if (strcmp(cmd.command, CMD_MDOWN) == 0)  handle_mdown(cmd);
    else if (strcmp(cmd.command, CMD_MUP) == 0)    handle_mup(cmd);
    else if (strcmp(cmd.command, CMD_SCROLL) == 0) handle_scroll(cmd);
    else send_nack(cmd.cmd_id, ERR_UNKNOWN_CMD);

    executing = false;
}

// --- Serial reader ---

void check_serial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (line_pos > 0) {
                line_buf[line_pos] = '\0';
                ParsedCommand cmd = parse_line(line_buf);
                if (cmd.valid) {
                    execute_command(cmd);
                }
                line_pos = 0;
            }
        } else if (line_pos < MAX_LINE_LEN - 1) {
            line_buf[line_pos++] = c;
        }
    }
}

// --- Entry points ---

void setup() {
    Serial.begin(115200);

    USB.VID(0x046D);
    USB.PID(0xC077);
    USB.productName("USB Optical Mouse");
    USB.manufacturerName("Logitech");

    Mouse.begin();
    USB.begin();
}

void loop() {
    check_serial();
}
