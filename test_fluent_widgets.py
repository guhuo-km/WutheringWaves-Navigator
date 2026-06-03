"""
PyQt-Fluent-Widgets 测试程序
用于验证库是否正确安装和工作
"""

import sys

# 关键修复：环境检测
# 该环境同时安装了 PyQt-Fluent-Widgets (基于 PyQt5) 和 PySide6-Fluent-Widgets。
# 且 `qfluentwidgets` 模块实际上是 PyQt5 版本的。
# 因此，这个测试程序必须使用 PyQt5 来运行，否则无法混合使用 PySide6 的布局和 PyQt5 的组件。

try:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
    PYSIDE6 = False
except ImportError:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
    PYSIDE6 = True

from qfluentwidgets import (
    # 按钮
    PushButton, PrimaryPushButton, TogglePushButton,
    ToolButton, TransparentPushButton,
    # 输入组件
    LineEdit, ComboBox, CheckBox, RadioButton,
    SpinBox, DoubleSpinBox, Slider, SwitchButton,
    # 文本组件
    BodyLabel, CaptionLabel, TitleLabel, SubtitleLabel, StrongBodyLabel,
    TextEdit,
    # 容器组件
    SimpleCardWidget, ElevatedCardWidget,
    # 对话框
    MessageBox, InfoBar, InfoBarPosition,
    # 主题
    setTheme, Theme, isDarkTheme, toggleTheme,
    # 图标
    FluentIcon as FIF
)


class FluentWidgetsTestWindow(QWidget):
    """Fluent Widgets 组件测试窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt-Fluent-Widgets 测试")
        self.resize(800, 700)

        # 主布局
        main_layout = QVBoxLayout(self)

        # 标题
        title = TitleLabel("Fluent Widgets 组件测试")
        main_layout.addWidget(title)

        # 主题切换按钮
        theme_btn = PushButton("切换主题 (浅色/深色)")
        theme_btn.clicked.connect(lambda: toggleTheme())
        main_layout.addWidget(theme_btn)

        # === 按钮测试卡片 ===
        button_card = self.create_button_test_card()
        main_layout.addWidget(button_card)

        # === 输入控件测试卡片 ===
        input_card = self.create_input_test_card()
        main_layout.addWidget(input_card)

        # === 文本组件测试卡片 ===
        text_card = self.create_text_test_card()
        main_layout.addWidget(text_card)

        # === 对话框测试卡片 ===
        dialog_card = self.create_dialog_test_card()
        main_layout.addWidget(dialog_card)

        main_layout.addStretch()

    def create_button_test_card(self):
        """创建按钮测试卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)

        # 标题
        layout.addWidget(SubtitleLabel("按钮组件测试"))

        # 按钮行
        btn_layout = QHBoxLayout()

        # 普通按钮
        normal_btn = PushButton("普通按钮")
        normal_btn.clicked.connect(lambda: self.show_info("点击了普通按钮"))
        btn_layout.addWidget(normal_btn)

        # 主要按钮
        primary_btn = PrimaryPushButton("主要按钮")
        primary_btn.clicked.connect(lambda: self.show_info("点击了主要按钮"))
        btn_layout.addWidget(primary_btn)

        # 带图标的按钮
        icon_btn = PushButton(FIF.FOLDER, "带图标按钮")
        icon_btn.clicked.connect(lambda: self.show_info("点击了图标按钮"))
        btn_layout.addWidget(icon_btn)

        # 工具按钮
        tool_btn = ToolButton(FIF.SETTING)
        tool_btn.clicked.connect(lambda: self.show_info("点击了工具按钮"))
        btn_layout.addWidget(tool_btn)

        # 透明按钮
        trans_btn = TransparentPushButton("透明按钮")
        trans_btn.clicked.connect(lambda: self.show_info("点击了透明按钮"))
        btn_layout.addWidget(trans_btn)

        layout.addLayout(btn_layout)

        # 切换按钮行
        toggle_layout = QHBoxLayout()

        # 切换按钮
        self.toggle_btn = TogglePushButton("切换按钮 (未选中)")
        self.toggle_btn.toggled.connect(self.on_toggle_changed)
        toggle_layout.addWidget(self.toggle_btn)

        layout.addLayout(toggle_layout)

        return card

    def create_input_test_card(self):
        """创建输入控件测试卡片"""
        card = ElevatedCardWidget()
        layout = QVBoxLayout(card)

        # 标题
        layout.addWidget(SubtitleLabel("输入控件测试"))

        # 输入框
        input_layout = QHBoxLayout()
        input_layout.addWidget(BodyLabel("输入框:"))
        line_edit = LineEdit()
        line_edit.setPlaceholderText("请输入文本...")
        input_layout.addWidget(line_edit)
        layout.addLayout(input_layout)

        # 下拉框
        combo_layout = QHBoxLayout()
        combo_layout.addWidget(BodyLabel("下拉框:"))
        combo = ComboBox()
        combo.addItems(["选项1", "选项2", "选项3"])
        combo_layout.addWidget(combo)
        layout.addLayout(combo_layout)

        # 数字输入框
        spinbox_layout = QHBoxLayout()
        spinbox_layout.addWidget(BodyLabel("数字输入:"))
        spinbox = SpinBox()
        spinbox.setRange(0, 100)
        spinbox.setValue(50)
        spinbox_layout.addWidget(spinbox)
        layout.addLayout(spinbox_layout)

        # 复选框和单选框
        check_layout = QHBoxLayout()
        checkbox = CheckBox("复选框")
        check_layout.addWidget(checkbox)

        radio1 = RadioButton("单选1")
        radio2 = RadioButton("单选2")
        radio1.setChecked(True)
        check_layout.addWidget(radio1)
        check_layout.addWidget(radio2)

        # 开关按钮
        switch = SwitchButton("开关按钮")
        check_layout.addWidget(switch)

        layout.addLayout(check_layout)

        # 滑块
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(BodyLabel("滑块:"))
        slider = Slider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(50)
        self.slider_label = BodyLabel("50")
        slider.valueChanged.connect(lambda v: self.slider_label.setText(str(v)))
        slider_layout.addWidget(slider)
        slider_layout.addWidget(self.slider_label)
        layout.addLayout(slider_layout)

        return card

    def create_text_test_card(self):
        """创建文本组件测试卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)

        # 标题
        layout.addWidget(SubtitleLabel("文本组件测试"))

        # 不同类型的标签
        layout.addWidget(StrongBodyLabel("加粗文本标签"))
        layout.addWidget(BodyLabel("正常文本标签 - 用于显示普通信息"))
        layout.addWidget(CaptionLabel("小字标签 - 用于显示次要信息"))

        # 文本编辑器
        text_edit = TextEdit()
        text_edit.setPlaceholderText("这是一个 Fluent 风格的文本编辑器...")
        text_edit.setMaximumHeight(100)
        layout.addWidget(text_edit)

        return card

    def create_dialog_test_card(self):
        """创建对话框测试卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)

        # 标题
        layout.addWidget(SubtitleLabel("对话框测试"))

        # 按钮布局
        btn_layout = QHBoxLayout()

        # 消息框按钮
        msg_btn = PushButton("显示消息框")
        msg_btn.clicked.connect(self.show_message_box)
        btn_layout.addWidget(msg_btn)

        # InfoBar 按钮
        info_btn = PushButton("显示成功提示")
        info_btn.clicked.connect(self.show_success_info)
        btn_layout.addWidget(info_btn)

        warn_btn = PushButton("显示警告提示")
        warn_btn.clicked.connect(self.show_warning_info)
        btn_layout.addWidget(warn_btn)

        error_btn = PushButton("显示错误提示")
        error_btn.clicked.connect(self.show_error_info)
        btn_layout.addWidget(error_btn)

        layout.addLayout(btn_layout)

        return card

    def on_toggle_changed(self, checked):
        """切换按钮状态改变"""
        if checked:
            self.toggle_btn.setText("切换按钮 (已选中)")
            self.show_info("切换按钮: 已选中")
        else:
            self.toggle_btn.setText("切换按钮 (未选中)")
            self.show_info("切换按钮: 未选中")

    def show_info(self, message):
        """显示普通信息"""
        InfoBar.info(
            title='提示',
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2000,
            parent=self
        )

    def show_success_info(self):
        """显示成功提示"""
        InfoBar.success(
            title='成功',
            content='操作已成功完成！',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def show_warning_info(self):
        """显示警告提示"""
        InfoBar.warning(
            title='警告',
            content='请注意检查您的输入！',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def show_error_info(self):
        """显示错误提示"""
        InfoBar.error(
            title='错误',
            content='发生了一个错误，请稍后重试。',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=self
        )

    def show_message_box(self):
        """显示消息框"""
        w = MessageBox(
            '消息框标题',
            '这是一个 Fluent Design 风格的消息框。\n\n'
            '它比传统的 QMessageBox 更美观，并且支持主题切换。',
            self
        )
        w.exec()


if __name__ == '__main__':
    # 启用高 DPI 缩放
    if not PYSIDE6:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    window = FluentWidgetsTestWindow()
    window.show()

    sys.exit(app.exec_()) if not PYSIDE6 else sys.exit(app.exec())
