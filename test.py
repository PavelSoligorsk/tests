import os
import uuid
import base64
import boto3
from botocore.config import Config

# ===== ВСТАВЬ СВОИ ДАННЫЕ =====
R2_ACCESS_KEY_ID = "befe408c5eb37b8615974744ba18e2a7"
R2_SECRET_ACCESS_KEY = "e6081b27bf6ed64a6c844fe28e8086b5ed4250362b495754bc897596faf5e936"
R2_ENDPOINT_URL = "https://3e61544d45ec8411a96f0985c1726ab8.r2.cloudflarestorage.com"
R2_BUCKET_NAME = "edu-backet"
R2_PUBLIC_URL = "https://3e61544d45ec8411a96f0985c1726ab8.r2.cloudflarestorage.com"
# ===============================

# Тестовое изображение (красный пиксель 1x1 в base64)
TEST_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

def test_upload():
    print("🚀 Начинаем тест загрузки в Cloudflare R2...")
    
    try:
        # 1. Настраиваем клиент
        print("📡 Подключаюсь к R2...")
        s3_client = boto3.client(
            's3',
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name='auto',
            config=Config(signature_version='s3v4')
        )
        print("✅ Клиент создан")
        
        # 2. Декодируем base64 в байты
        print("🖼️ Декодирую изображение...")
        image_bytes = base64.b64decode(TEST_IMAGE_BASE64)
        print(f"✅ Размер изображения: {len(image_bytes)} байт")
        
        # 3. Генерируем имя файла
        filename = f"test/{uuid.uuid4().hex}.png"
        print(f"📝 Имя файла: {filename}")
        
        # 4. Загружаем в R2
        print("☁️ Загружаю в R2...")
        s3_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=filename,
            Body=image_bytes,
            ContentType='image/png',
            CacheControl='max-age=31536000'
        )
        print("✅ Загрузка успешна!")
        
        # 5. Формируем публичную ссылку
        file_url = f"{R2_PUBLIC_URL}/{filename}"
        print(f"\n🔗 Прямая ссылка на изображение:")
        print(f"{file_url}")
        
        # 6. Проверяем, что ссылка работает
        print("\n🌐 Проверяю доступность ссылки...")
        import requests
        response = requests.get(file_url)
        if response.status_code == 200:
            print("✅ Ссылка работает! Изображение доступно.")
        else:
            print(f"⚠️ Ссылка вернула статус: {response.status_code}")
        
        print("\n🎉 ТЕСТ ПРОЙДЕН УСПЕШНО!")
        return file_url
        
    except Exception as e:
        print(f"\n❌ ОШИБКА: {str(e)}")
        return None

def list_test_files():
    """Показывает все тестовые файлы в бакете"""
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name='auto',
            config=Config(signature_version='s3v4')
        )
        
        print("\n📂 Файлы в бакете test/:")
        response = s3_client.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix="test/")
        
        if 'Contents' in response:
            for obj in response['Contents']:
                print(f"  - {obj['Key']} ({obj['Size']} байт)")
        else:
            print("  (пусто)")
            
    except Exception as e:
        print(f"Ошибка при списке: {e}")

if __name__ == "__main__":
    print("=" * 50)
    print("ТЕСТ ЗАГРУЗКИ В CLOUDFLARE R2")
    print("=" * 50)
    
    # Загружаем тестовое изображение
    url = test_upload()
    
    if url:
        print("\n" + "=" * 50)
        print("СОХРАНИ ЭТУ ССЫЛКУ ДЛЯ ПРОВЕРКИ:")
        print(url)
        print("=" * 50)
        
        # Показываем все тестовые файлы
        list_test_files()

input("\nНажми Enter для выхода...")