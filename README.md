# Portfolio Project Manager

Ứng dụng web local dùng để thêm, sắp xếp và xóa project trong portfolio.

## Chạy trên Windows

1. Cài Python 3.10 trở lên.
2. Giải nén thư mục.
3. Nhấp đúp `run_windows.bat`.
4. Trang quản lý: `http://127.0.0.1:5000/admin`
5. Trang portfolio: `http://127.0.0.1:5000/`

## Quy tắc tên ảnh

- Ảnh chính project 1: `img/img1.png`
- Ảnh con: `img/img1_1.png`, `img/img1_2.png`, ...
- Khi chèn, kéo thả, hoặc xóa project, ứng dụng tự đổi tên toàn bộ ảnh liên quan.
- Ảnh tải lên được chuyển thành PNG tự động.

## Dữ liệu

Thông tin project được lưu trong `projects.json`.

Các trường:
- `id`: mã nội bộ
- `order`: thứ tự
- `title`: tên project
- `hashtags`: danh sách hashtag
- `description`: mô tả
- `link`: đường dẫn project

Không nên sửa file JSON khi ứng dụng đang chạy.

## Đưa file cũ vào

- Chép `avt.jpg`, CV HTML và các tài nguyên cần thiết vào cùng thư mục với `app.py`.
- Ảnh project nên được quản lý thông qua trang `/admin`.
