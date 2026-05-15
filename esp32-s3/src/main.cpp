#include <Arduino.h>
#include "USB.h"
#include "USBHIDMouse.h"
#include "USBHIDAbsoluteMouse.h"
#include "USBHIDKeyboard.h"
#include "commands.h"

USBHIDMouse Mouse;
USBHIDAbsoluteMouse AbsMouse;
USBHIDKeyboard Keyboard;

static char line_buf[MAX_LINE_LEN];
static int line_pos = 0;
static bool executing = false;

// --- Response helpers ---

void send_ack(int cmd_id) {
    Serial.printf("<%d,%s>\n", cmd_id, RSP_ACK);
}

void send_nack(int cmd_id, int error_code) {
    Serial.printf("<%d,%s,%d>\n", cmd_id, RSP_NACK, error_code);
}

void send_pong() {
    Serial.printf("<0,%s>\n", RSP_PONG);
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

    int target_x = atoi(cmd.params[0]);
    int target_y = atoi(cmd.params[1]);
    int duration_ms = (cmd.param_count >= 3) ? atoi(cmd.params[2]) : 0;

    if (duration_ms <= 0) {
        Mouse.move(target_x, target_y);
    } else {
        int steps = duration_ms / STEP_INTERVAL_MS;
        if (steps < 1) steps = 1;
        float dx = (float)target_x / steps;
        float dy = (float)target_y / steps;
        float accum_x = 0, accum_y = 0;
        for (int i = 0; i < steps; i++) {
            accum_x += dx;
            accum_y += dy;
            int mx = (int)accum_x;
            int my = (int)accum_y;
            if (mx != 0 || my != 0) {
                Mouse.move(mx, my);
            }
            accum_x -= mx;
            accum_y -= my;
            delay(STEP_INTERVAL_MS);
        }
    }
    send_ack(cmd.cmd_id);
}

void handle_moveto(const ParsedCommand& cmd) {
    if (cmd.param_count < 2) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    int abs_x = atoi(cmd.params[0]);
    int abs_y = atoi(cmd.params[1]);

    abs_x = constrain(abs_x, 0, 32767);
    abs_y = constrain(abs_y, 0, 32767);

    AbsMouse.move(abs_x, abs_y);
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

void handle_drag(const ParsedCommand& cmd) {
    if (cmd.param_count < 4) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    int x1 = atoi(cmd.params[0]);
    int y1 = atoi(cmd.params[1]);
    int x2 = atoi(cmd.params[2]);
    int y2 = atoi(cmd.params[3]);
    int duration_ms = (cmd.param_count >= 5) ? atoi(cmd.params[4]) : 200;

    Mouse.move(x1, y1);
    delay(10);
    Mouse.press(MOUSE_LEFT);
    delay(20);

    int dx = x2 - x1;
    int dy = y2 - y1;
    int steps = duration_ms / STEP_INTERVAL_MS;
    if (steps < 1) steps = 1;

    float step_x = (float)dx / steps;
    float step_y = (float)dy / steps;
    float accum_x = 0, accum_y = 0;

    for (int i = 0; i < steps; i++) {
        accum_x += step_x;
        accum_y += step_y;
        int mx = (int)accum_x;
        int my = (int)accum_y;
        if (mx != 0 || my != 0) {
            Mouse.move(mx, my);
        }
        accum_x -= mx;
        accum_y -= my;
        delay(STEP_INTERVAL_MS);
    }

    delay(10);
    Mouse.release(MOUSE_LEFT);
    send_ack(cmd.cmd_id);
}

void handle_scroll(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    int amount = atoi(cmd.params[0]);
    Mouse.move(0, 0, amount);
    send_ack(cmd.cmd_id);
}

void handle_key(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    uint8_t keycode = (uint8_t)atoi(cmd.params[0]);
    int hold_ms = (cmd.param_count >= 2) ? atoi(cmd.params[1]) : 50;

    Keyboard.press(keycode);
    delay(hold_ms);
    Keyboard.release(keycode);
    send_ack(cmd.cmd_id);
}

void handle_combo(const ParsedCommand& cmd) {
    if (cmd.param_count < 2) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    uint8_t mod = (uint8_t)atoi(cmd.params[0]);
    uint8_t keycode = (uint8_t)atoi(cmd.params[1]);

    if (mod & 0x01) Keyboard.press(KEY_LEFT_CTRL);
    if (mod & 0x02) Keyboard.press(KEY_LEFT_SHIFT);
    if (mod & 0x04) Keyboard.press(KEY_LEFT_ALT);
    if (mod & 0x08) Keyboard.press(KEY_LEFT_GUI);

    Keyboard.press(keycode);
    delay(50);
    Keyboard.releaseAll();
    send_ack(cmd.cmd_id);
}

void handle_reset(const ParsedCommand& cmd) {
    Mouse.release(MOUSE_LEFT);
    Mouse.release(MOUSE_RIGHT);
    Mouse.release(MOUSE_MIDDLE);
    Keyboard.releaseAll();
    send_ack(cmd.cmd_id);
}

// --- Dispatcher ---

void execute_command(const ParsedCommand& cmd) {
    if (strcmp(cmd.command, CMD_PING) == 0)       { send_pong(); return; }
    if (strcmp(cmd.command, CMD_RESET) == 0)      { handle_reset(cmd); return; }

    if (executing) { send_nack(cmd.cmd_id, ERR_BUSY); return; }
    executing = true;

    if      (strcmp(cmd.command, CMD_MOVE) == 0)   handle_move(cmd);
    else if (strcmp(cmd.command, CMD_MOVETO) == 0) handle_moveto(cmd);
    else if (strcmp(cmd.command, CMD_CLICK) == 0)  handle_click(cmd);
    else if (strcmp(cmd.command, CMD_DCLICK) == 0) handle_dclick(cmd);
    else if (strcmp(cmd.command, CMD_DRAG) == 0)   handle_drag(cmd);
    else if (strcmp(cmd.command, CMD_SCROLL) == 0) handle_scroll(cmd);
    else if (strcmp(cmd.command, CMD_KEY) == 0)    handle_key(cmd);
    else if (strcmp(cmd.command, CMD_COMBO) == 0)  handle_combo(cmd);
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
    Mouse.begin();
    AbsMouse.begin();
    Keyboard.begin();
    USB.begin();

    unsigned long start = millis();
    while (!Serial && millis() - start < 5000) { delay(10); }
}

void loop() {
    check_serial();
}
