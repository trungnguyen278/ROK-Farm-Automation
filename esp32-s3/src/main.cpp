#include <Arduino.h>
#include "USB.h"
#include "USBHIDMouse.h"
#include "USBHIDKeyboard.h"
#include "commands.h"
USBHIDMouse Mouse;
USBHIDAbsoluteMouse AbsMouse;
USBHIDKeyboard Keyboard;

static char line_buf[MAX_LINE_LEN];
static int line_pos = 0;
static bool executing = false;
static bool idle_suppressed = false;
static unsigned long last_cmd_time = 0;
static unsigned long last_mouse_idle = 0;

static PathPoint path_buf[MAX_PATH_POINTS];
static int path_len = 0;

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
        if (dx != 0 || dy != 0) delay(random(6, 10));
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

// --- Keyboard key mapping ---

uint8_t map_key(const char* name) {
    if (strcmp(name, "ESC") == 0)    return KEY_ESC;
    if (strcmp(name, "TAB") == 0)    return KEY_TAB;
    if (strcmp(name, "ENTER") == 0)  return KEY_RETURN;
    if (strcmp(name, "SPACE") == 0)  return ' ';
    if (strcmp(name, "BKSP") == 0)   return KEY_BACKSPACE;
    if (strcmp(name, "UP") == 0)     return KEY_UP_ARROW;
    if (strcmp(name, "DOWN") == 0)   return KEY_DOWN_ARROW;
    if (strcmp(name, "LEFT") == 0)   return KEY_LEFT_ARROW;
    if (strcmp(name, "RIGHT") == 0)  return KEY_RIGHT_ARROW;
    if (strcmp(name, "ALT") == 0)    return KEY_LEFT_ALT;
    if (strcmp(name, "CTRL") == 0)   return KEY_LEFT_CTRL;
    if (strcmp(name, "SHIFT") == 0)  return KEY_LEFT_SHIFT;
    if (strcmp(name, "F1") == 0)     return KEY_F1;
    if (strcmp(name, "F2") == 0)     return KEY_F2;
    if (strcmp(name, "F3") == 0)     return KEY_F3;
    if (strcmp(name, "F4") == 0)     return KEY_F4;
    if (strcmp(name, "F5") == 0)     return KEY_F5;
    if (strcmp(name, "F6") == 0)     return KEY_F6;
    if (strcmp(name, "F7") == 0)     return KEY_F7;
    if (strcmp(name, "F8") == 0)     return KEY_F8;
    if (strcmp(name, "F9") == 0)     return KEY_F9;
    if (strcmp(name, "F10") == 0)    return KEY_F10;
    if (strcmp(name, "F11") == 0)    return KEY_F11;
    if (strcmp(name, "F12") == 0)    return KEY_F12;
    if (strcmp(name, "DEL") == 0)    return KEY_DELETE;
    if (strcmp(name, "HOME") == 0)   return KEY_HOME;
    if (strcmp(name, "END") == 0)    return KEY_END;
    if (strcmp(name, "PGUP") == 0)   return KEY_PAGE_UP;
    if (strcmp(name, "PGDN") == 0)   return KEY_PAGE_DOWN;
    if (strlen(name) == 1) return (uint8_t)name[0];
    return 0;
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
        int steps = duration_ms / 8;
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
            delay(random(6, 10));
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

void handle_key(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    uint8_t key = map_key(cmd.params[0]);
    if (key == 0) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    int hold_ms = (cmd.param_count >= 2) ? atoi(cmd.params[1]) : 50;

    Keyboard.press(key);
    delay(hold_ms);
    Keyboard.release(key);
    send_ack(cmd.cmd_id);
}

void handle_combo(const ParsedCommand& cmd) {
    if (cmd.param_count < 2) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }

    int hold_ms = 50;
    int key_count = cmd.param_count;

    char* endp;
    long last_val = strtol(cmd.params[cmd.param_count - 1], &endp, 10);
    if (*endp == '\0' && last_val > 0 && last_val < 5000) {
        hold_ms = (int)last_val;
        key_count--;
    }

    for (int i = 0; i < key_count; i++) {
        uint8_t key = map_key(cmd.params[i]);
        if (key == 0) {
            Keyboard.releaseAll();
            send_nack(cmd.cmd_id, ERR_INVALID_PARAMS);
            return;
        }
        Keyboard.press(key);
        delay(random(5, 20));
    }
    delay(hold_ms);
    Keyboard.releaseAll();
    send_ack(cmd.cmd_id);
}

void handle_moveto(const ParsedCommand& cmd) {
    if (cmd.param_count < 2) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    int x = atoi(cmd.params[0]);
    int y = atoi(cmd.params[1]);
    x = constrain(x, 0, 32767);
    y = constrain(y, 0, 32767);
    AbsMouse.move(x, y);
    send_ack(cmd.cmd_id);
}

void handle_drag(const ParsedCommand& cmd) {
    if (cmd.param_count < 4) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    int x1 = constrain(atoi(cmd.params[0]), 0, 32767);
    int y1 = constrain(atoi(cmd.params[1]), 0, 32767);
    int x2 = constrain(atoi(cmd.params[2]), 0, 32767);
    int y2 = constrain(atoi(cmd.params[3]), 0, 32767);
    int dur_ms = (cmd.param_count >= 5) ? atoi(cmd.params[4]) : 200;

    AbsMouse.move(x1, y1);
    delay(random(30, 60));
    Mouse.press(MOUSE_LEFT);
    delay(random(20, 50));

    int steps = max(1, dur_ms / 10);
    float dx = (float)(x2 - x1) / steps;
    float dy = (float)(y2 - y1) / steps;
    float cx = x1, cy = y1;
    for (int i = 0; i < steps; i++) {
        cx += dx;
        cy += dy;
        AbsMouse.move(constrain((int)cx, 0, 32767), constrain((int)cy, 0, 32767));
        delay(random(8, 12));
    }
    AbsMouse.move(x2, y2);
    delay(random(20, 50));
    Mouse.release(MOUSE_LEFT);
    send_ack(cmd.cmd_id);
}

void handle_idle(const ParsedCommand& cmd) {
    if (cmd.param_count < 1) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    idle_suppressed = (atoi(cmd.params[0]) == 1);
    send_ack(cmd.cmd_id);
}

void handle_path_clr(const ParsedCommand& cmd) {
    path_len = 0;
    send_ack(cmd.cmd_id);
}

void handle_path_pt(const ParsedCommand& cmd) {
    if (cmd.param_count < 3) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    if (path_len >= MAX_PATH_POINTS) { send_nack(cmd.cmd_id, ERR_PATH_FULL); return; }
    path_buf[path_len].x = constrain(atoi(cmd.params[0]), 0, 32767);
    path_buf[path_len].y = constrain(atoi(cmd.params[1]), 0, 32767);
    path_buf[path_len].delay_ms = constrain(atoi(cmd.params[2]), 0, 255);
    path_len++;
    send_ack(cmd.cmd_id);
}

void execute_path() {
    for (int i = 0; i < path_len; i++) {
        AbsMouse.move(path_buf[i].x, path_buf[i].y);
        if (path_buf[i].delay_ms > 0) {
            int jitter = (path_buf[i].delay_ms > 4) ? random(-2, 3) : 0;
            delay(max(1, path_buf[i].delay_ms + jitter));
        }
    }
}

void handle_path_go(const ParsedCommand& cmd) {
    if (path_len == 0) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    execute_path();
    path_len = 0;
    send_ack(cmd.cmd_id);
}

void handle_path_drag(const ParsedCommand& cmd) {
    if (path_len == 0) { send_nack(cmd.cmd_id, ERR_INVALID_PARAMS); return; }
    // Move to first point, press, execute path, release
    AbsMouse.move(path_buf[0].x, path_buf[0].y);
    delay(random(20, 40));
    Mouse.press(MOUSE_LEFT);
    delay(random(10, 25));
    execute_path();
    delay(random(10, 25));
    Mouse.release(MOUSE_LEFT);
    path_len = 0;
    send_ack(cmd.cmd_id);
}

void handle_reset(const ParsedCommand& cmd) {
    Mouse.release(MOUSE_LEFT);
    Mouse.release(MOUSE_RIGHT);
    Mouse.release(MOUSE_MIDDLE);
    Keyboard.releaseAll();
    idle_suppressed = false;
    send_ack(cmd.cmd_id);
}

// --- Dispatcher ---

void execute_command(const ParsedCommand& cmd) {
    last_cmd_time = millis();

    if (strcmp(cmd.command, CMD_PING) == 0)       { send_pong(); return; }
    if (strcmp(cmd.command, CMD_RESET) == 0)      { handle_reset(cmd); return; }
    if (strcmp(cmd.command, CMD_IDLE) == 0)       { handle_idle(cmd); return; }
    if (strcmp(cmd.command, CMD_PATH_CLR) == 0)   { handle_path_clr(cmd); return; }
    if (strcmp(cmd.command, CMD_PATH_PT) == 0)    { handle_path_pt(cmd); return; }

    if (executing) { send_nack(cmd.cmd_id, ERR_BUSY); return; }
    executing = true;

    if      (strcmp(cmd.command, CMD_MOVE) == 0)       handle_move(cmd);
    else if (strcmp(cmd.command, CMD_MOVETO) == 0)     handle_moveto(cmd);
    else if (strcmp(cmd.command, CMD_CLICK) == 0)      handle_click(cmd);
    else if (strcmp(cmd.command, CMD_DCLICK) == 0)     handle_dclick(cmd);
    else if (strcmp(cmd.command, CMD_DRAG) == 0)       handle_drag(cmd);
    else if (strcmp(cmd.command, CMD_MDOWN) == 0)      handle_mdown(cmd);
    else if (strcmp(cmd.command, CMD_MUP) == 0)        handle_mup(cmd);
    else if (strcmp(cmd.command, CMD_SCROLL) == 0)     handle_scroll(cmd);
    else if (strcmp(cmd.command, CMD_KEY) == 0)        handle_key(cmd);
    else if (strcmp(cmd.command, CMD_COMBO) == 0)      handle_combo(cmd);
    else if (strcmp(cmd.command, CMD_PATH_GO) == 0)    handle_path_go(cmd);
    else if (strcmp(cmd.command, CMD_PATH_DRAG) == 0)  handle_path_drag(cmd);
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

// --- Idle HID noise (autonomous, based on command inactivity) ---

void idle_noise() {
    if (executing || idle_suppressed) return;
    unsigned long now = millis();
    bool idle = (now - last_cmd_time > 2000);
    if (!idle) return;

    if (now - last_mouse_idle > (unsigned long)random(500, 3000)) {
        int8_t dx = random(-1, 2);
        int8_t dy = random(-1, 2);
        if (dx != 0 || dy != 0) {
            Mouse.move(dx, dy, 0);
        }
        last_mouse_idle = now;
    }
}

// --- Entry points ---

void setup() {
    Serial.begin(115200);

    USB.VID(0x046D);
    USB.PID(0xC52B);
    USB.productName("USB Receiver");
    USB.manufacturerName("Logitech");

    uint16_t versions[] = {0x2901, 0x2407, 0x3001, 0x2200};
    USB.firmwareVersion(versions[esp_random() % 4]);

    char serial_buf[16];
    uint32_t chip_id = (uint32_t)(ESP.getEfuseMac() >> 16);
    uint32_t rand_part = esp_random() & 0xFFFF;
    snprintf(serial_buf, sizeof(serial_buf), "%04X%04X",
             (uint16_t)(chip_id & 0xFFFF), (uint16_t)rand_part);
    USB.serialNumber(serial_buf);

    Mouse.begin();
    AbsMouse.begin();
    Keyboard.begin();
    USB.begin();

    last_cmd_time = millis();
    last_mouse_idle = millis();
}

void loop() {
    check_serial();
    idle_noise();
}
