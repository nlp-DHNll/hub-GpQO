"""
一键启动器。

    python run.py                  # http://本机IP:8000
    python run.py --port 9000
    python run.py --https          # 自签证书，手机可直接调用摄像头

手机在同一 Wi-Fi 下访问终端打印的地址即可；iPhone/Android 若提示证书不安全，
点「继续访问 / 高级 → 继续」后摄像头权限才会被授予。
"""
from __future__ import annotations

import argparse
import ipaddress
import socket
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CERT_DIR = BASE_DIR / ".certs"
sys.path.insert(0, str(BASE_DIR))

import config as cfg  # noqa: E402


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def ensure_cert() -> tuple[Path, Path]:
    """生成带 LAN IP 的自签证书（仅首次）。"""
    CERT_DIR.mkdir(exist_ok=True)
    cert, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if cert.exists() and key.exists():
        return cert, key

    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    ip = lan_ip()
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "corridor-risk-local")]
    )
    now = datetime.now(timezone.utc)
    san = [x509.DNSName("localhost"), x509.DNSName("corridor-risk-local")]
    for addr in {ip, "127.0.0.1"}:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(addr)))
        except ValueError:
            pass

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(k.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(k, hashes.SHA256())
    )

    key.write_bytes(
        k.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    print(f"已生成自签证书：{cert}")
    return cert, key


def main() -> None:
    parser = argparse.ArgumentParser(description="楼道消防隐患识别服务")
    parser.add_argument("--host", default=cfg.HOST)
    parser.add_argument("--port", type=int, default=cfg.PORT)
    parser.add_argument("--https", action="store_true", help="启用 HTTPS（手机调用摄像头需要）")
    args = parser.parse_args()

    import uvicorn

    ip = lan_ip()
    scheme = "https" if args.https else "http"
    kw: dict = {}
    if args.https:
        cert, key = ensure_cert()
        kw.update(ssl_certfile=str(cert), ssl_keyfile=str(key))

    print("\n" + "=" * 56)
    print("  楼道消防安全隐患识别")
    print("=" * 56)
    print(f"  本机： {scheme}://127.0.0.1:{args.port}")
    print(f"  手机： {scheme}://{ip}:{args.port}   (需同一 Wi-Fi)")
    models = [m for m in cfg.available_models() if m["available"]]
    if models:
        print(f"  模型： {', '.join(m['label'] for m in models)}")
    else:
        print("  模型： 未配置 Key -> 演示模式（.env 填 DASHSCOPE_API_KEY 后重启）")
    if not args.https:
        print("  提示：手机浏览器用 http 时无法直接开摄像头，会自动改为系统相机拍照。")
    print("=" * 56 + "\n")

    uvicorn.run("app:app", host=args.host, port=args.port, log_level="info", **kw)


if __name__ == "__main__":
    main()
