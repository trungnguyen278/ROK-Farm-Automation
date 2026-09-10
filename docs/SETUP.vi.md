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

### ⚠️ Mạch ESP32-S3 có HAI cổng USB — khi chạy farm phải cắm CẢ HAI

Nhìn chữ in cạnh cổng trên bo mạch. Hai cổng làm hai việc khác nhau:

| Cổng | Việc | Lúc nạp | Lúc chạy farm |
|---|---|---|---|
| **UART** / **COM** | Nhận lệnh từ máy tính | **Bắt buộc** | **Bắt buộc** |
| **USB** / **OTG** | Đóng vai chuột + bàn phím thật | không cần | **Bắt buộc** |

- **Nạp firmware**: chỉ cần cổng UART/COM. Cắm vào cổng kia thì app báo
  *"Sai cổng USB"* và không nạp được.
- **Chạy farm**: phải cắm **cả hai cổng vào máy tính**. Thiếu cổng USB gốc thì
  mạch vẫn trả lời PING bình thường nhưng **con trỏ chuột không hề nhúc nhích** —
  đây là lỗi khó đoán nhất, vì mọi thứ trông như đang hoạt động.

Cổng USB gốc cũng **bắt buộc dùng cáp truyền dữ liệu**. Cáp sạc để nó có điện,
trả lời PING, mà HID không bao giờ hiện ra.

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

### Bước 3. Cửa sổ có 4 thẻ — làm từ trái sang phải

| Thẻ | Việc |
|---|---|
| **1. Mạch ESP32** | Xem đã thấy mạch chưa, và bấm **Nạp firmware vào mạch** |
| **2. Chạy farm** | **Bắt đầu farm** / **Dừng farm** |
| **3. Discord** | Dán token + ID, **Lưu cài đặt**, rồi **Bật bot** |
| **4. Thống kê** | Số mỏ đã farm, lượt hành quân, tỉ lệ thành công, vì sao hỏng |

Ô trạng thái trên cùng mỗi thẻ tự cập nhật 2 giây một lần, nên bạn cứ cắm cáp
vào là thấy nó đổi ngay, không cần bấm gì.

### Bước 4. Thẻ 1 — nạp mạch

**Bạn không phải build gì cả.** Firmware dựng sẵn nằm trong thư mục `firmware/`.
App tự tìm mạch và tự biết mạch đã có firmware hay chưa.

Thẻ này cho một trong ba trạng thái, và trạng thái nào cũng kèm hướng dẫn ngay
bên dưới:

- **Đã thấy mạch ở COMxx** → bấm **Nạp firmware vào mạch** (khoảng 15 giây,
  đừng rút cáp). Nếu mạch đã chạy đúng rồi thì bạn không cần bấm.
- **Sai cổng USB** → app thấy cổng USB gốc chứ không phải cổng UART. Chuyển cáp.
- **Không thấy mạch** → app liệt kê 4 thứ cần kiểm tra theo thứ tự: cáp, cắm đủ
  hai cổng, đúng loại mạch (ESP32-**S3** N16R8, ESP32 thường không chạy được),
  và cách giữ nút BOOT nếu nạp mãi vẫn lỗi.

### Bước 5. Thẻ 2 — chạy farm

Bấm **Bắt đầu farm**.

> **Nên ĐÓNG Rise of Kingdoms trước khi bấm.** Bot tự mở game lấy. Nếu bám vào
> một client đang chạy sẵn ở chế độ nền, bot sẽ **hỏng 3 mỏ đầu tiên**: ROK
> ngừng vẽ lại màn hình khi không ở tiền cảnh, hệ thống chụp màn hình cứ trả
> về đúng khung hình cũ, và bot thất bại liên tiếp khoảng 75 giây.

App sẽ hỏi lại nếu bạn vừa dùng chuột trong 5 phút qua — vì mạch sẽ giành chuột
với bạn.

**Đóng cửa sổ app KHÔNG dừng farm.** Farm chạy tách rời, cố ý như vậy để tắt/mở
app không giết một phiên đang chạy. Muốn dừng hẳn thì bấm **Dừng farm**.

### Bước 6. Thẻ 3 — điều khiển bằng Discord (tuỳ chọn)

Bỏ qua cũng được, farm vẫn chạy bằng thẻ 2. Xem phần hướng dẫn Discord ở dưới.

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
.venv\Scripts\python -m app.main            # cua so (GUI)
.venv\Scripts\python -m app.main menu       # menu chu, cho terminal
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

Thẻ **3. Discord** trong app: dán 3 giá trị vào ô, bấm **Lưu cài đặt**, rồi bấm
**Bật bot**. Bot sẽ nhắn "Bot online" vào kênh đã ghim.

Ba ô đó chính là file `.env` cạnh `ROK Farm.exe`. File này **chứa token** — đừng
gửi cho ai.

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
| Farm chạy nhưng chuột không nhúc nhích | **Chưa cắm cổng USB thứ hai** (cổng USB/OTG). Mạch vẫn trả lời PING nên mọi thứ trông bình thường. Cắm nốt là chạy. Nếu đã cắm đủ: còn tiến trình farm cũ giữ cổng COM — thẻ 2 → Dừng farm. |
| Hỏng 3 mỏ đầu mỗi lần chạy | Bạn bật farm khi game đã mở sẵn. Đóng game rồi bật lại. |
| Windows hiện hộp thoại UAC rồi đứng im | Chạy app bằng **Run as administrator**. |
| Đóng cửa sổ app mà farm vẫn chạy | Đúng như thiết kế. Farm chạy tách rời. Dừng bằng **Dừng farm** ở thẻ 2, hoặc `!stop`. |
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
