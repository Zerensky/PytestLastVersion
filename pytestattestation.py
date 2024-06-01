# В этот раз я работаю с кодом который мне удалось сделать по семинару
# Задание 1.
#Переделать все шаги позитивных тестов на выполнение по SSH. Проверить работу.

# Задание 1 Переделать все шаги позитивных тестов на выполнение по SSH. Проверить работу.

#Для выполнения шагов тестов по SSH была исползована библиотека paramiko, 

# Установка paramiko
# pip install paramiko

import pytest
import subprocess
import zipfile
import tarfile
import zlib
import os
import time
import io
import yaml
import paramiko
from my_archive_tool import calculate_crc32, list_files, extract_files

# Чтение конфига из YAML файла
with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

package_name = config['package_name']
ssh_user = config['ssh_user']
ssh_password = config['ssh_password']
ssh_address = config['ssh_address']
archive_type = 'zip'  # Можно поменять на 'tar', 'gz' и т.д.

# Утилиты для выполнения команд по SSH (чуть с ума не сошёл пока разобрался)
def ssh_command(client, command):
    stdin, stdout, stderr = client.exec_command(command)
    stdout.channel.recv_exit_status()  # Блокирует выполнение до завершения команды
    return stdout.read().decode(), stderr.read().decode()

# Фикстура для установки пакета и настройки SSH сервера
@pytest.fixture(scope="session", autouse=True)
def setup_ssh_server():
    # Установка пакета
    subprocess.run(["sudo", "apt", "install", "-y", package_name], check=True)
    
    # Включение и запуск службы sshd
    subprocess.run(["sudo", "systemctl", "enable", "sshd"], check=True)
    subprocess.run(["sudo", "systemctl", "start", "sshd"], check=True)
    
    # Создание пользователя user
    subprocess.run(["sudo", "useradd", ssh_user, "-m"], check=True)
    
    # Задание пароля для пользователя
    process = subprocess.Popen(["sudo", "passwd", ssh_user], stdin=subprocess.PIPE)
    process.communicate(input=f"{ssh_password}\n{ssh_password}\n".encode())
    
    # Выдача прав суперпользователя пользователю
    subprocess.run(["sudo", "usermod", "-aG", "sudo", ssh_user], check=True)
    
    yield
    
    # Удаление пакета после выполнения всех тестов
    subprocess.run(["sudo", "apt", "remove", "-y", package_name], check=True)
    subprocess.run(["sudo", "apt", "purge", "-y", package_name], check=True)

# Фикстура для создания SSH клиента
@pytest.fixture(scope="session")
def ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ssh_address, username=ssh_user, password=ssh_password)
    yield client
    client.close()

# Фикстура для получения времени старта шага в формате, пригодном для journalctl
@pytest.fixture
def start_time():
    return time.strftime("%Y-%m-%d %H:%M:%S")

# Фикстура для создания тестового архива по SSH
@pytest.fixture
def create_test_zip(ssh_client, tmp_path, start_time):
    archive_path = tmp_path / f"test_archive.{archive_type}"
    if archive_type == 'zip':
        # Создаем zip архив локально и отправляем его по SSH
        with zipfile.ZipFile(archive_path, 'w') as zip_ref:
            zip_ref.writestr("file1.txt", "This is the content of file1.")
            zip_ref.writestr("file2.txt", "This is the content of file2.")
        sftp = ssh_client.open_sftp()
        sftp.put(archive_path, f"/home/{ssh_user}/test_archive.zip")
        sftp.close()
    elif archive_type == 'tar':
        # Создаем tar архив локально и отправляем его по SSH
        with tarfile.open(archive_path, 'w') as tar_ref:
            file1 = tarfile.TarInfo("file1.txt")
            file1_data = b"This is the content of file1."
            file1.size = len(file1_data)
            tar_ref.addfile(file1, io.BytesIO(file1_data))

            file2 = tarfile.TarInfo("file2.txt")
            file2_data = b"This is the content of file2."
            file2.size = len(file2_data)
            tar_ref.addfile(file2, io.BytesIO(file2_data))
        sftp = ssh_client.open_sftp()
        sftp.put(archive_path, f"/home/{ssh_user}/test_archive.tar")
        sftp.close()
    else:
        raise ValueError(f"Unsupported archive type: {archive_type}")

    # Сохранение системного лога за время работы шага
    end_time = time.strftime("%Y-%m-%d %H:%M:%S")
    log_file_path = tmp_path / "system_log.txt"
    with open(log_file_path, "a") as log_file:
        log_file.write(f"\nLogs from {start_time} to {end_time}:\n")
        stdout, stderr = ssh_command(ssh_client, f"journalctl --since \"{start_time}\" --until \"{end_time}\"")
        log_file.write(stdout)
    
    return archive_path

# Фикстура для логирования статистики после каждого теста
@pytest.fixture(autouse=True)
def log_stats_after_test(request, tmp_path, start_time, ssh_client):
    yield
    end_time = time.strftime("%Y-%m-%d %H:%M:%S")
    stat_file_path = tmp_path / "stat.txt"
    with open(stat_file_path, "a") as stat_file:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        archive_path = request.getfixturevalue('create_test_zip')
        files = list_files(archive_path)
        num_files = len(files)
        file_size = os.path.getsize(archive_path)
        stdout, stderr = ssh_command(ssh_client, "cat /proc/loadavg")
        loadavg = stdout.strip()
        stat_file.write(f"{timestamp}, {num_files}, {file_size}, {loadavg}\n")
    
    # Сохранение системного лога за время работы шага
    log_file_path = tmp_path / "system_log.txt"
    with open(log_file_path, "a") as log_file:
        log_file.write(f"\nLogs from {start_time} to {end_time}:\n")
        stdout, stderr = ssh_command(ssh_client, f"journalctl --since \"{start_time}\" --until \"{end_time}\"")
        log_file.write(stdout)

# Тесты
def test_calculate_crc32(create_test_zip, ssh_client):
    sftp = ssh_client.open_sftp()
    remote_archive_path = f"/home/{ssh_user}/test_archive.{archive_type}"
    local_archive_path = create_test_zip
    sftp.get(remote_archive_path, local_archive_path)
    sftp.close()

    crc_file1 = calculate_crc32(local_archive_path, "file1.txt")
    crc_file2 = calculate_crc32(local_archive_path, "file2.txt")

    # Manually calculate CRC32 for comparison
    manual_crc_file1 = zlib.crc32(b"This is the content of file1.") & 0xFFFFFFFF
    manual_crc_file2 = zlib.crc32(b"This is the content of file2.") & 0xFFFFFFFF

    assert crc_file1 == manual_crc_file1
    assert crc_file2 == manual_crc_file2

def test_list_files(create_test_zip, ssh_client):
    sftp = ssh_client.open_sftp()
    remote_archive_path = f"/home/{ssh_user}/test_archive.{archive_type}"
    local_archive_path = create_test_zip
    sftp.get(remote_archive_path, local_archive_path)
    sftp.close()

    files = list_files(local_archive_path)
    assert "file1.txt" in files
    assert "file2.txt" in files
    assert len(files) == 2

def test_extract_files(create_test_zip, tmp_path, ssh_client):
    extract_path = tmp_path / "extracted"
    remote_archive_path = f"/home/{ssh_user}/test_archive.{archive_type}"
    local_archive_path = create_test_zip

    sftp = ssh_client.open_sftp()
    sftp.get(remote_archive_path, local_archive_path)
    sftp.close()

    extract_files(local_archive_path, extract_path)
    assert (extract_path / "file1.txt").exists()
    assert (extract_path / "file2.txt").exists()

    with open(extract_path / "file1.txt") as f:
        assert f.read() == "This is the content of file1."

    with open(extract_path / "file2.txt") as f:
        assert f.read() == "This is the content of file2."


# памятка из вики для меня (вечно забываю)
#Фикстура setup_ssh_server:
#Устанавливает пакет, настраивает SSH сервер, создает пользователя, задает пароль и выдает права суперпользователя.
#Добавлена команда удаления пакета после выполнения всех тестов.
#Фикстура ssh_client:
#Создает SSH клиент для выполнения команд по SSH.
#Фикстура start_time:
#Возвращает текущее время в формате, пригодном для использования с `journal

# Задание 2. (дополнительное задание)
# Переделать все шаги негативных тестов на выполнение по SSH. Проверить работу.

# Мой пример  негативных тестов, которые проверяют:

# 1. Попытка доступа к несуществующему файлу в архиве.
# 2. Попытка распаковать несуществующий архив.
# 3. Попытка рассчитать хеш для несуществующего файла.

import pytest
import zipfile
import tarfile
import zlib
import os
import time
import io
import yaml
import paramiko
from my_archive_tool import calculate_crc32, list_files, extract_files

# Чтение конфигурации из YAML файла
with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

package_name = config['package_name']
ssh_user = config['ssh_user']
ssh_password = config['ssh_password']
ssh_address = config['ssh_address']
archive_type = 'zip'  # Можно поменять на 'tar', 'gz' и т.д.

# Утилиты для выполнения команд по SSH
def ssh_command(client, command):
    stdin, stdout, stderr = client.exec_command(command)
    stdout.channel.recv_exit_status()  # Блокирует выполнение до завершения команды
    return stdout.read().decode(), stderr.read().decode()

# Фикстура для установки пакета и настройки SSH сервера
@pytest.fixture(scope="session", autouse=True)
def setup_ssh_server():
    # Установка пакета
    subprocess.run(["sudo", "apt", "install", "-y", package_name], check=True)
    
    # Включение и запуск службы sshd
    subprocess.run(["sudo", "systemctl", "enable", "sshd"], check=True)
    subprocess.run(["sudo", "systemctl", "start", "sshd"], check=True)
    
    # Создание пользователя
    subprocess.run(["sudo", "useradd", ssh_user, "-m"], check=True)
    
    # Задание пароля для пользователя
    process = subprocess.Popen(["sudo", "passwd", ssh_user], stdin=subprocess.PIPE)
    process.communicate(input=f"{ssh_password}\n{ssh_password}\n".encode())
    
    # Выдача прав суперпользователя пользователю
    subprocess.run(["sudo", "usermod", "-aG", "sudo", ssh_user], check=True)
    
    yield
    
    # Удаление пакета после выполнения всех тестов
    subprocess.run(["sudo", "apt", "remove", "-y", package_name], check=True)
    subprocess.run(["sudo", "apt", "purge", "-y", package_name], check=True)

# Фикстура для создания SSH клиента
@pytest.fixture(scope="session")
def ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ssh_address, username=ssh_user, password=ssh_password)
    yield client
    client.close()

# Фикстура для получения времени старта шага в формате, пригодном для journalctl
@pytest.fixture
def start_time():
    return time.strftime("%Y-%m-%d %H:%M:%S")

# Фикстура для создания тестового архива по SSH
@pytest.fixture
def create_test_zip(ssh_client, tmp_path, start_time):
    archive_path = tmp_path / f"test_archive.{archive_type}"
    if archive_type == 'zip':
        # Создаем zip архив локально и отправляем его по SSH
        with zipfile.ZipFile(archive_path, 'w') as zip_ref:
            zip_ref.writestr("file1.txt", "This is the content of file1.")
            zip_ref.writestr("file2.txt", "This is the content of file2.")
        sftp = ssh_client.open_sftp()
        sftp.put(archive_path, f"/home/{ssh_user}/test_archive.zip")
        sftp.close()
    elif archive_type == 'tar':
        # Создаем tar архив локально и отправляем его по SSH
        with tarfile.open(archive_path, 'w') as tar_ref:
            file1 = tarfile.TarInfo("file1.txt")
            file1_data = b"This is the content of file1."
            file1.size = len(file1_data)
            tar_ref.addfile(file1, io.BytesIO(file1_data))

            file2 = tarfile.TarInfo("file2.txt")
            file2_data = b"This is the content of file2."
            file2.size = len(file2_data)
            tar_ref.addfile(file2, io.BytesIO(file2_data))
        sftp = ssh_client.open_sftp()
        sftp.put(archive_path, f"/home/{ssh_user}/test_archive.tar")
        sftp.close()
    else:
        raise ValueError(f"Unsupported archive type: {archive_type}")

    # Сохранение системного лога за время работы шага
    end_time = time.strftime("%Y-%m-%d %H:%M:%S")
    log_file_path = tmp_path / "system_log.txt"
    with open(log_file_path, "a") as log_file:
        log_file.write(f"\nLogs from {start_time} to {end_time}:\n")
        stdout, stderr = ssh_command(ssh_client, f"journalctl --since \"{start_time}\" --until \"{end_time}\"")
        log_file.write(stdout)
    
    return archive_path

# Фикстура для логирования статистики после каждого теста
@pytest.fixture(autouse=True)
def log_stats_after_test(request, tmp_path, start_time, ssh_client):
    yield
    end_time = time.strftime("%Y-%m-%d %H:%M:%S")
    stat_file_path = tmp_path / "stat.txt"
    with open(stat_file_path, "a") as stat_file:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        archive_path = request.getfixturevalue('create_test_zip')
        files = list_files(archive_path)
        num_files = len(files)
        file_size = os.path.getsize(archive_path)
        stdout, stderr = ssh_command(ssh_client, "cat /proc/loadavg")
        loadavg = stdout.strip()
        stat_file.write(f"{timestamp}, {num_files}, {file_size}, {loadavg}\n")
    
    # Сохранение системного лога за время работы шага
    log_file_path = tmp_path / "system_log.txt"
    with open(log_file_path, "a") as log_file:
        log_file.write(f"\nLogs from {start_time} to {end_time}:\n")
        stdout, stderr = ssh_command(ssh_client, f"journalctl --since \"{start_time}\" --until \"{end_time}\"")
        log_file.write(stdout)

# Негативные тесты
def test_calculate_crc32_nonexistent_file(create_test_zip, ssh_client):
    sftp = ssh_client.open_sftp()
    remote_archive_path = f"/home/{ssh_user}/test_archive.{archive_type}"
    local_archive_path = create_test_zip
    sftp.get(remote_archive_path, local_archive_path)
    sftp.close()

    with pytest.raises(KeyError):
        calculate_crc32(local_archive_path, "nonexistent_file.txt")

def test_list_files_nonexistent_archive(ssh_client):
    with pytest.raises(FileNotFoundError):
        sftp = ssh_client.open_sftp()
        non_existent_path = f"/home/{ssh_user}/nonexistent_archive.zip"
        sftp.get(non_existent_path, "nonexistent_archive.zip")
        sftp.close()

def test_extract_files_nonexistent_archive(ssh_client, tmp_path):
    extract_path = tmp_path / "extracted"
    non_existent_path = f"/home/{ssh_user}/nonexistent_archive.zip"
    with pytest.raises(FileNotFoundError):
        sftp = ssh_client.open_sftp()
        sftp.get(non_existent_path, "nonexistent_archive.zip")
        sftp.close()
        extract_files("nonexistent_archive.zip", extract_path)

#Негативные тесты:

# Тесты проверяют:
# Попытка доступа к несуществующему файлу в архиве вызывает KeyError.
# Попытка работы с несуществующим архивом вызывает FileNotFoundError.

# и самое главное от чего я в восторге что config.yaml остается без изменений :D 





