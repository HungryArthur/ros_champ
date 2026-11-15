# TurtleBro: один скрипт для задания

В `main.py` находится весь учебный сценарий: выезд с парковки, светофор,
шлагбаум, поиск картины по ArUco и возвращение. Он импортирует библиотеку
производителя `turtlebro_py` и OpenCV. Собственных классов навигации нет.

| Ветка | Для чего |
|---|---|
| [`main`](https://github.com/HungryArthur/ros_champ/tree/main) | Настоящий TurtleBro с ROS 1 и Python 3 |
| [`webots-training`](https://github.com/HungryArthur/ros_champ/tree/webots-training) | Тот же `main.py` и готовая карта Webots |

**Это сценарий для нашей известной учебной карты.** Робот едет по заранее
заданным точкам с помощью одометрии. Следования разметке камерой здесь нет.
Для другой карты нужно измерить маршрут и изменить координаты; цвета светофора
и словарь маркеров тоже нужно сверить с заданием. Физический робот пока недоступен
для испытаний: проверены API производителя, сценарий на модели и тесты.

## Windows: подключение и запуск

На ноутбуке нужны редактор, Git и клиент OpenSSH. ROS работает **на роботе**.
Имя пользователя, IP и пароль выдаёт организатор; адрес ниже — пример.

1. Проверьте в PowerShell:

   ```powershell
   ssh -V
   ```

   Если команды нет, выполните в PowerShell **от администратора**:

   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
   ```

2. Скачайте проект или откройте уже существующую папку:

   ```powershell
   git clone https://github.com/HungryArthur/ros_champ.git
   cd ros_champ
   $robot = 'pi@192.168.1.100'
   ```

3. Отредактируйте `main.py`. Отправьте файл и зависимости на робота:

   ```powershell
   ssh $robot "mkdir -p ~/ros_champ"
   scp .\main.py .\requirements.txt "${robot}:ros_champ/"
   ssh $robot
   ```

4. Теперь вы **в Linux на роботе**. При первом подключении выполните подготовку
   из раздела ниже. Для обычного запуска:

   ```bash
   source ~/catkin_ws/devel/setup.bash
   export PYTHONPATH="$HOME/catkin_ws/src/turtlebro_extra/turtlebro_py/src:$PYTHONPATH"
   cd ~/ros_champ
   .venv/bin/python main.py
   ```

После изменения программы повторите `scp` в локальном PowerShell и запуск
в SSH-терминале. `Ctrl+C` прерывает скрипт; блок `finally` отправляет остановку.

## Linux: подключение и запуск

Следующие команды выполняются **на вашем ноутбуке**. Для Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git openssh-client
git clone https://github.com/HungryArthur/ros_champ.git
cd ros_champ
ROBOT='pi@192.168.1.100'
```

Отредактируйте `main.py`, затем отправьте его и подключитесь:

```bash
ssh "$ROBOT" 'mkdir -p ~/ros_champ'
scp main.py requirements.txt "$ROBOT:ros_champ/"
ssh "$ROBOT"
```

Теперь **на роботе**, после однократной подготовки ниже:

```bash
source ~/catkin_ws/devel/setup.bash
export PYTHONPATH="$HOME/catkin_ws/src/turtlebro_extra/turtlebro_py/src:$PYTHONPATH"
cd ~/ros_champ
.venv/bin/python main.py
```

Если вы работаете непосредственно в Linux робота, команды `ssh` и `scp`
пропускаются: достаточно открыть папку с программой и выполнить этот запуск.

## Один раз: библиотеки на роботе

Нужен готовый образ TurtleBro с **ROS 1, Python 3 и работающими драйверами**.
ROS 2 использует другой API. Эта инструкция предполагает стандартный
`~/catkin_ws`; если организатор указал другой workspace, замените путь.

Библиотека производителя ставится отдельно от нашего репозитория. Если
`~/catkin_ws/src/turtlebro_extra` уже существует, повторять клонирование не нужно.
По [инструкции производителя](https://github.com/voltbro/turtlebro_extra/tree/master/turtlebro_py):

```bash
cd ~/catkin_ws/src
git clone https://github.com/voltbro/turtlebro_extra.git
cd ~/catkin_ws
catkin_make --pkg=turtlebro_extra
source devel/setup.bash
```

Для Python-зависимостей создайте окружение с доступом к системным ROS-модулям:

```bash
sudo apt install -y python3-venv python3-pip
cd ~/ros_champ
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
export PYTHONPATH="$HOME/catkin_ws/src/turtlebro_extra/turtlebro_py/src:$PYTHONPATH"
.venv/bin/python -c "from turtlebro_py import TurtleBro; import cv2; print('OpenCV:', cv2.__version__); print('ArUco:', hasattr(cv2, 'aruco'))"
```

Последняя команда проверяет импорт, **не создавая робота и не двигая его**.
`rospy` и типы сообщений ставятся вместе с ROS, а не через `requirements.txt`.
NumPy ограничен версией 1.x для окружения ROS 1; OpenCV — веткой до 4.12.

При работе через VS Code удобно использовать
[Remote — SSH](https://code.visualstudio.com/docs/remote/ssh):
`Ctrl+Shift+P` → `Remote-SSH: Connect to Host...`, затем открыть
`~/ros_champ` на роботе и выбрать его `.venv/bin/python`.
Локальный Python Windows не содержит ROS: предупреждение о `turtlebro_py`
в локальном редакторе не означает, что библиотека отсутствует на роботе.

## Что менять в скрипте

| Строка или функция | Назначение |
|---|---|
| `TARGET = 3` | Какую картину искать: 1, 2 или 3 |
| `DICT_4X4_50` | Словарь ArUco; должен совпадать с маркерами задания |
| `go(x, y)` | Точка в метрах относительно старта и осей учебной карты |
| `face(degrees)` | Направление относительно осей карты |
| `corner(x, y, start)` | Поворот по дуге радиусом 0.675 м |
| `green()` | Проверка зелёного сигнала по изображению камеры |
| `wait_until(...)` | Ожидание условия не дольше 25 секунд |
| `image()` | Получение кадра с отдельным таймаутом 3 секунды |

В нашей карте старт смотрит вниз, ось x направлена вправо, y — вверх.
Скрипт запоминает исходную позу и переносит точки маршрута в координаты одометрии.
Для точного заезда важны калибровка одометрии, размеры поля и исходная парковка.
Ожидание шлагбаума использует луч лидара прямо впереди; высота перекладины
должна попадать в плоскость сканирования.

Полезные команды оригинальной библиотеки:

```python
tb.forward(0.2)            # Вперёд на 20 см.
tb.left(90)                # Налево на 90 градусов.
tb.right(90)               # Направо на 90 градусов.
tb.turn(-45)               # Поворот на 45 градусов направо.
tb.goto(x, y)              # Поворот и движение к точке в координатах одометрии.
tb.photo                   # Изображение BGR для OpenCV.
tb.lidar_distance()         # Расстояние впереди, метры.
tb.wait(1)                 # Подождать секунду.
tb.say("Привет мир")
tb.vel_pub.publish()       # Нулевая скорость, остановка.
```

В библиотеке производителя нет `tb.stop()`, `tb.reset()` или `tb.drive()`.
`TurtleBro()` сам создаёт ROS-узел; отдельный `rospy.init_node()` не нужен.
Перед соревнованием уточните разрешённые библиотеки, версию ROS, темы датчиков,
словарь маркеров и точное условие задания.

## Тренировка без робота

Готовая карта и совместимый адаптер сохранены в отдельной ветке:

```bash
git clone --branch webots-training https://github.com/HungryArthur/ros_champ.git ros_champ_webots
```

В ней находится **та же копия `main.py`**. Команды установки Webots и запуска
для Windows/Linux описаны в README этой ветки. В основной ветке нет локального
`turtlebro_py.py`, который мог бы подменить библиотеку производителя.

Тесты сценария без ROS: `python -m unittest discover -s tests -v`.
Они проверяют логику на заменах датчиков; физические испытания выполняются отдельно.

Источники: [TurtleBro API](https://github.com/voltbro/turtlebro_extra/tree/master/turtlebro_py),
[OpenCV ArUco](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html),
[OpenSSH для Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse),
[Python venv](https://docs.python.org/3/library/venv.html).
