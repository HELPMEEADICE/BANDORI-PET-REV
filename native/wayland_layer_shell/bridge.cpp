#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <LayerShellQt/Shell>
#include <LayerShellQt/Window>
#include <QMargins>
#include <QSize>
#include <QWindow>
#include <basewrapper.h>

namespace {

QWindow *qWindowFromPython(PyObject *object)
{
    if (!object) {
        PyErr_SetString(PyExc_TypeError, "expected a PySide6.QtGui.QWindow");
        return nullptr;
    }
    PyObject *module = PyImport_ImportModule("PySide6.QtGui");
    if (!module) {
        return nullptr;
    }
    PyObject *typeObject = PyObject_GetAttrString(module, "QWindow");
    Py_DECREF(module);
    if (!typeObject || !PyType_Check(typeObject)) {
        Py_XDECREF(typeObject);
        PyErr_SetString(PyExc_RuntimeError, "could not resolve PySide6.QtGui.QWindow");
        return nullptr;
    }
    const int isInstance = PyObject_IsInstance(object, typeObject);
    if (isInstance <= 0) {
        Py_DECREF(typeObject);
        if (isInstance == 0) {
            PyErr_SetString(PyExc_TypeError, "expected a PySide6.QtGui.QWindow");
        }
        return nullptr;
    }
    if (!Shiboken::Object::isValid(reinterpret_cast<SbkObject *>(object))) {
        Py_DECREF(typeObject);
        PyErr_SetString(PyExc_RuntimeError, "the QWindow wrapper is no longer valid");
        return nullptr;
    }
    auto *window = reinterpret_cast<QWindow *>(Shiboken::Object::cppPointer(
        reinterpret_cast<SbkObject *>(object),
        reinterpret_cast<PyTypeObject *>(typeObject)));
    Py_DECREF(typeObject);
    if (!window) {
        PyErr_SetString(PyExc_TypeError, "object does not wrap a QWindow");
    }
    return window;
}

LayerShellQt::Window::Layer parseLayer(const char *value)
{
    const QByteArray name(value ? value : "");
    if (name == "overlay") {
        return LayerShellQt::Window::LayerOverlay;
    }
    if (name == "bottom") {
        return LayerShellQt::Window::LayerBottom;
    }
    if (name == "background") {
        return LayerShellQt::Window::LayerBackground;
    }
    return LayerShellQt::Window::LayerTop;
}

LayerShellQt::Window::KeyboardInteractivity parseKeyboard(const char *value)
{
    const QByteArray name(value ? value : "");
    if (name == "exclusive") {
        return LayerShellQt::Window::KeyboardInteractivityExclusive;
    }
    if (name == "on_demand") {
        return LayerShellQt::Window::KeyboardInteractivityOnDemand;
    }
    return LayerShellQt::Window::KeyboardInteractivityNone;
}

PyObject *initialize(PyObject *, PyObject *)
{
    LayerShellQt::Shell::useLayerShell();
    Py_RETURN_NONE;
}

PyObject *qtVersion(PyObject *, PyObject *)
{
    return PyUnicode_FromString(QT_VERSION_STR);
}

PyObject *prepare(PyObject *, PyObject *args)
{
    PyObject *pyWindow = nullptr;
    int x = 0;
    int y = 0;
    int width = 0;
    int height = 0;
    const char *layer = nullptr;
    const char *keyboard = nullptr;
    const char *scope = nullptr;
    if (!PyArg_ParseTuple(
            args,
            "Oiiiisss",
            &pyWindow,
            &x,
            &y,
            &width,
            &height,
            &layer,
            &keyboard,
            &scope)) {
        return nullptr;
    }
    QWindow *window = qWindowFromPython(pyWindow);
    if (!window) {
        return nullptr;
    }
    auto *surface = LayerShellQt::Window::get(window);
    surface->setScope(QString::fromUtf8(scope));
    surface->setAnchors(
        LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorLeft);
    surface->setExclusiveZone(0);
    surface->setDesiredSize(QSize(qMax(1, width), qMax(1, height)));
    surface->setMargins(QMargins(qMax(0, x), qMax(0, y), 0, 0));
    surface->setLayer(parseLayer(layer));
    surface->setKeyboardInteractivity(parseKeyboard(keyboard));
    surface->setScreenConfiguration(
        LayerShellQt::Window::ScreenFromQWindow);
    surface->setCloseOnDismissed(false);
    Py_RETURN_NONE;
}

PyObject *setMargins(PyObject *, PyObject *args)
{
    PyObject *pyWindow = nullptr;
    int x = 0;
    int y = 0;
    if (!PyArg_ParseTuple(args, "Oii", &pyWindow, &x, &y)) {
        return nullptr;
    }
    QWindow *window = qWindowFromPython(pyWindow);
    if (!window) {
        return nullptr;
    }
    LayerShellQt::Window::get(window)->setMargins(
        QMargins(qMax(0, x), qMax(0, y), 0, 0));
    Py_RETURN_NONE;
}

PyObject *setSize(PyObject *, PyObject *args)
{
    PyObject *pyWindow = nullptr;
    int width = 0;
    int height = 0;
    if (!PyArg_ParseTuple(args, "Oii", &pyWindow, &width, &height)) {
        return nullptr;
    }
    QWindow *window = qWindowFromPython(pyWindow);
    if (!window) {
        return nullptr;
    }
    LayerShellQt::Window::get(window)->setDesiredSize(
        QSize(qMax(1, width), qMax(1, height)));
    Py_RETURN_NONE;
}

PyObject *setLayer(PyObject *, PyObject *args)
{
    PyObject *pyWindow = nullptr;
    const char *layer = nullptr;
    if (!PyArg_ParseTuple(args, "Os", &pyWindow, &layer)) {
        return nullptr;
    }
    QWindow *window = qWindowFromPython(pyWindow);
    if (!window) {
        return nullptr;
    }
    LayerShellQt::Window::get(window)->setLayer(parseLayer(layer));
    Py_RETURN_NONE;
}

PyObject *setKeyboard(PyObject *, PyObject *args)
{
    PyObject *pyWindow = nullptr;
    const char *keyboard = nullptr;
    if (!PyArg_ParseTuple(args, "Os", &pyWindow, &keyboard)) {
        return nullptr;
    }
    QWindow *window = qWindowFromPython(pyWindow);
    if (!window) {
        return nullptr;
    }
    LayerShellQt::Window::get(window)->setKeyboardInteractivity(
        parseKeyboard(keyboard));
    Py_RETURN_NONE;
}

PyObject *rebindOutput(PyObject *, PyObject *args)
{
    PyObject *pyWindow = nullptr;
    if (!PyArg_ParseTuple(args, "O", &pyWindow)) {
        return nullptr;
    }
    QWindow *window = qWindowFromPython(pyWindow);
    if (!window) {
        return nullptr;
    }
    const bool wasVisible = window->isVisible();
    if (wasVisible) {
        window->setVisible(false);
    }
    window->destroy();
    window->create();
    if (wasVisible) {
        window->setVisible(true);
    }
    Py_RETURN_NONE;
}

PyMethodDef methods[] = {
    {"initialize", initialize, METH_NOARGS, "Initialize LayerShellQt."},
    {"qt_version", qtVersion, METH_NOARGS, "Return the compile-time Qt version."},
    {"prepare", prepare, METH_VARARGS, "Prepare a QWindow as a layer surface."},
    {"set_margins", setMargins, METH_VARARGS, "Set top-left layer margins."},
    {"set_size", setSize, METH_VARARGS, "Set desired layer surface size."},
    {"set_layer", setLayer, METH_VARARGS, "Set top/overlay layer."},
    {"set_keyboard", setKeyboard, METH_VARARGS, "Set keyboard interactivity."},
    {"rebind_output", rebindOutput, METH_VARARGS, "Recreate a layer surface on its QWindow screen."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_layer_shell",
    "BandoriPet LayerShellQt bridge",
    -1,
    methods,
};

} // namespace

PyMODINIT_FUNC PyInit__layer_shell()
{
    return PyModule_Create(&module);
}
