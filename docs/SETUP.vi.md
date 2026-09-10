# Hướng dẫn cài đặt — ROK Farm

Dành cho người **không rành máy tính**. Làm đúng thứ tự là chạy được.

English version: [SETUP.en.md](SETUP.en.md)

---

## Bạn cần những gì

| | |
|---|---|
| Máy tính | Windows 10 hoặc 11 |
| Game | Rise of Kingdoms bản PC (đã cài, đã đăng nhập được ít nhất 1 lần) |
| Mạch | ESP32-S3 DevKitC-1 (loại **N16R8**) |
| Cáp | Cáp USB **truyền dữ liệu** — xem cảnh báo ở dưới |
| Discord | Tài khoản Discord (nếu muốn điều khiển từ điện thoại) |

### ⚠️ Cáp USB — lỗi hay gặp nhất

Cáp chỉ-để-sạc và cáp truyền dữ liệu **trông y hệt nhau**. Cắm nhầm cáp sạc thì
máy tính không thấy mạch, và màn hình sẽ báo "không tìm thấy mạch" y như khi
bạn chưa cắm gì.

**Nếu app báo không thấy mạch, việc đầu tiên là đổi cáp khác.**

### ⚠️ Mạch ESP32-S3 có HAI cổng USB

Nhìn kỹ chữ in cạnh cổng trên bo mạch:

- **UART** hoặc **COM** — cắm vào cổng này
- **USB** hoặc **OTG** — cổng còn lại, app **không nạp** được qua cổng này

Cắm nhầm thì app sẽ nói ra: *"Thấy cổng USB gốc của mạch — hãy chuyển cáp sang
cổng UART/COM"*.

---

## Cách 1 — Dùng bản đóng gói (khuyên dùng)

Không cần cài Python, không cần cài gì cả.

### Bước 1. Giải nén

Giải nén `ROK-Farm-portable.zip` ra một thư mục **không có tiếng Việt có dấu**,
ví dụ `D:\ROKFarm`.

> Đừng chạy thẳng trong file zip. Windows mở nó ở thư mục tạm, và mọi thứ app
> ghi ra (ảnh chụp màn hình, log, cấu hình) sẽ biến mất.

### Bước 2. Chạy app

Nhấp phải `ROK Farm.exe` → **Run as administrator**.

> Vì sao cần quyền admin: `launcher.exe` của Rise of Kingdoms đòi quyền
> administrator. Nếu app có sẵn quyền đó, launcher chạy im lặng. Nếu không,
> Windows hiện hộp thoại UAC — và **bot không bấm hộ được**, vì màn hình bảo
> mật của Windows vô hình với mọi cách chụp màn hình.

### Bước 3. Chọn mục 1 — Cài đặt lần đầu

App sẽ dẫn qua 5 bước. Mỗi bước đều nói rõ nó tìm thấy gì trước khi thay đổi
gì, nên **chạy lại nhiều lần vẫn an toàn** — đó cũng là cách sửa một bước bị lỗi.

| Bước | App làm gì | Bạn làm gì |
|---|---|---|
| 1 | Kiểm tra thư viện | Không cần làm gì (bản đóng gói luôn đủ) |
| 2 | Tìm mạch, nạp firmware | Cắm mạch vào cổng UART/COM |
| 3 | Tìm Rise of Kingdoms | Dán đường dẫn nếu app không tự tìm ra |
| 4 | Cấu hình Discord | Dán token + user ID (xem phần dưới) |
| 5 | Tổng kết | Đọc xem có bước nào chưa xong |

**Bước 2 quan trọng nhất — và bạn không phải build gì cả.** Firmware đã được
dựng sẵn nằm trong thư mục `firmware/`. App tự tìm mạch, tự kiểm tra xem mạch
đã có firmware chưa, và chỉ nạp khi cần:

- Mạch đã có firmware → app hỏi PING, mạch trả PONG, app bỏ qua bước nạp
- Mạch còn trắng → app nạp, chờ mạch khởi động lại, rồi kiểm tra lại

Đừng rút cáp trong lúc nó đang nạp.

### Bước 4. Bắt đầu farm

Về menu chính → chọn **mục 2**.

> **Nên ĐÓNG Rise of Kingdoms trước khi bấm.** Bot tự mở game lấy. Nếu bám vào
> một client đang chạy sẵn ở chế độ nền, bot sẽ **hỏng 3 mỏ đầu tiên**: ROK
> ngừng vẽ lại màn hình khi không ở tiền cảnh, hệ thống chụp màn hình cứ trả
> về đúng khung hình cũ, và bot thất bại liên tiếp khoảng 75 giây.

---

## Cách 2 — Chạy từ mã nguồn

Dành cho người muốn sửa code.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Nạp mạch (dùng firmware dựng sẵn, không cần PlatformIO):

```powershell
.venv\Scripts\python tools\flash_board.py --check    # xem có gì đang cắm
.venv\Scripts\python tools\flash_board.py            # nạp nếu cần
```

Chạy:

```powershell
.venv\Scripts\python -m app.main            # menu
.venv\Scripts\python run_farm.py --count 2  # chạy thẳng
```

Dựng lại firmware từ mã nguồn C++ (chỉ khi bạn sửa `esp32-s3/src/main.cpp`):

```powershell
cd esp32-s3
pio run
```

> Chạy lệnh `pio` trong **PowerShell hoặc CMD**, đừng chạy trong Git Bash —
> bộ cài của pioarduino từ chối môi trường MSys/Mingw và báo lỗi khó hiểu.

---

## Điều khiển từ điện thoại qua Discord

Bot Discord là cách dùng hằng ngày: bật/tắt farm và xem ảnh màn hình từ xa.

### Tạo bot

1. Vào <https://discord.com/developers/applications> → **New Application** → đặt tên
2. Tab **Bot** → **Reset Token** → copy. **Token chỉ hiện MỘT lần.**
3. Vẫn tab đó, kéo xuống **Privileged Gateway Intents** → bật
   **MESSAGE CONTENT INTENT** → **Save Changes**

   Thiếu bước này thì bot nhận được tin nhắn rỗng và mọi lệnh im lặng không
   chạy. (Nhắn tin riêng cho bot thì vẫn được — đó là cách chữa cháy nếu quên.)

### Mời bot vào server

Lấy **Application ID** ở tab *General Information*, rồi mở:

```
https://discord.com/api/oauth2/authorize?client_id=<APPLICATION_ID>&permissions=101376&scope=bot
```

`101376` = xem kênh + gửi tin + gửi file + đọc lịch sử. Không hơn.

### Lấy ID của bạn

Discord → **Settings** → **Advanced** → bật **Developer Mode**. Rồi:

- Nhấp phải **tên bạn** → *Copy User ID* → đây là `DISCORD_OWNER_ID`
- Nhấp phải **kênh** muốn dùng → *Copy Channel ID* → `DISCORD_CHANNEL_ID` (tuỳ chọn)

> Bot **chỉ nghe lời một tài khoản duy nhất**. Lệnh từ người khác bị bỏ qua và
> ghi log. Không điền `DISCORD_OWNER_ID` thì bot **từ chối chạy** — thà không
> có điều khiển từ xa còn hơn có một cái ai cũng bấm được.

### Bật bot

Menu → **mục 4**. Bot sẽ nhắn "Bot online" vào kênh đã ghim.

### Các lệnh

| Lệnh | Việc |
|---|---|
| `!status` | Farm/watchdog/game đang thế nào, đếm số mỏ, còn chờ bao lâu |
| `!shot` | Ảnh màn hình game ngay lúc này |
| `!log [n]` | n dòng log gần nhất (mặc định 25) |
| `!report` | Báo cáo đầy đủ, gửi dạng file |
| `!start` | Bật farm + watchdog |
| `!start solo` | Chỉ farm, không có gì giám sát |
| `!start force` | Bật kể cả khi có người đang dùng máy |
| `!stop` | Dừng farm, đóng game, tắt rung chuột |
| `!stop keep` | Dừng farm nhưng để game chạy tiếp |

> `!start` sẽ **từ chối** nếu có người vừa dùng máy trong 5 phút qua — vì mạch
> ESP32 sẽ giành chuột với bạn. Đó là tính năng, không phải lỗi; muốn chạy
> thật thì gõ `!start force`.

---

## Khi có trục trặc

| Hiện tượng | Nguyên nhân hay gặp |
|---|---|
| "Không tìm thấy mạch" | Cáp chỉ để sạc. **Đổi cáp trước tiên.** |
| "Thấy cổng USB gốc" | Cắm nhầm cổng. Chuyển sang cổng **UART/COM**. |
| Nạp xong nhưng không trả lời | Rút ra cắm lại một lần. |
| Nạp thất bại liên tục | Giữ nút **BOOT** trên mạch trong lúc cắm cáp. |
| Mạch trả PING nhưng Windows chưa thấy chuột | Rút ra cắm lại. |
| Farm chạy nhưng chuột không nhúc nhích | Còn tiến trình farm cũ đang giữ cổng COM. Menu mục 3 → dừng hết. |
| Hỏng 3 mỏ đầu mỗi lần chạy | Bạn bật farm khi game đã mở sẵn. Đóng game rồi bật lại. |
| Windows hiện hộp thoại UAC rồi đứng im | Chạy app bằng **Run as administrator**. |
| Đóng cửa sổ menu mà farm vẫn chạy | Đúng như thiết kế. Farm chạy tách rời. Dừng bằng **mục 3** hoặc `!stop`. |
| Bot Discord không phản hồi trong server | Chưa bật **MESSAGE CONTENT INTENT**. |

### Chỗ xem log

```
logs\overnight\farm_run.log      farm đang làm gì
logs\overnight\watchdog.log      watchdog thấy gì
logs\overnight\discord_bot.log   bot nhận lệnh gì
screenshots\gem_farm_test\       ảnh bot đã chụp
```

---

## Những điều nên biết

**Đóng cửa sổ menu KHÔNG dừng farm.** Farm được bật ở chế độ tách rời, cố ý
như vậy: khởi động lại bot hay menu không được làm chết một phiên đang chạy.
Dừng hẳn bằng menu mục 3, hoặc `!stop` trong Discord.

**Dừng farm luôn trả lại chuột.** Nếu chỉ tắt tiến trình farm, mạch ESP32 vẫn
tiếp tục rung chuột nhè nhẹ — và đó là thứ bạn nhận ra đầu tiên khi định dùng
máy. Mục 3 và `!stop` đều tắt cái đó.

**Bot đóng game bằng ALT+F4, không phải kill tiến trình.** Kill cứng bị đọc là
crash.

**Ảnh `!shot` là toàn bộ màn hình game.** Để server Discord ở chế độ riêng tư.
