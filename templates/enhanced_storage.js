(function() {
    // 扩展sessionStorage为localStorage
    const originalSetItem = sessionStorage.setItem;
    sessionStorage.setItem = function(key, value) {
        localStorage.setItem(key, value);
        return originalSetItem.call(this, key, value);
    };

    // 保存所有表单数据
    function saveFormData() {
        const forms = document.querySelectorAll('form');
        forms.forEach((form, index) => {
            const formData = {};
            const inputs = form.querySelectorAll('input, select, textarea');
            inputs.forEach(input => {
                if (input.type !== 'password' && input.value) {
                    formData[input.name || input.id || index] = input.value;
                }
            });
            if (Object.keys(formData).length > 0) {
                localStorage.setItem(`form_${index}_${location.hostname}`, JSON.stringify(formData));
            }
        });
    }

    // 恢复表单数据
    function restoreFormData() {
        const forms = document.querySelectorAll('form');
        forms.forEach((form, index) => {
            const savedData = localStorage.getItem(`form_${index}_${location.hostname}`);
            if (savedData) {
                try {
                    const formData = JSON.parse(savedData);
                    Object.keys(formData).forEach(key => {
                        const input = form.querySelector(`[name="${key}"], [id="${key}"]`);
                        if (input && input.type !== 'password') {
                            input.value = formData[key];
                        }
                    });
                } catch(e) {}
            }
        });
    }

    // 监听页面加载和表单变化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', restoreFormData);
    } else {
        restoreFormData();
    }

    // 定期保存表单数据
    setInterval(saveFormData, 5000);

    // 在页面卸载前保存
    window.addEventListener('beforeunload', saveFormData);

    console.log('Enhanced storage system activated');
})();
