#include "live2d_gl_widget.h"

#include <QByteArray>
#include <QDebug>
#include <QMouseEvent>
#include <QOpenGLContext>
#include <QOpenGLExtraFunctions>
#include <QOpenGLFunctions>
#include <QSurfaceFormat>

#include <algorithm>
#include <cmath>
#include <utility>

namespace bandori {

void Live2dGlWidget::configureDefaultSurfaceFormat(bool vsync) {
    QSurfaceFormat format = QSurfaceFormat::defaultFormat();
    format.setAlphaBufferSize(8);
    format.setSamples(0);
    format.setDepthBufferSize(0);
    format.setStencilBufferSize(8);
    format.setSwapInterval(vsync ? 1 : 0);
    format.setVersion(2, 1);
    format.setRenderableType(QSurfaceFormat::OpenGL);
    format.setProfile(QSurfaceFormat::CompatibilityProfile);
    QSurfaceFormat::setDefaultFormat(format);
}

Live2dGlWidget::Live2dGlWidget(
    QString projectRoot,
    QString userModelsRoot,
    QString modelPath,
    ModelFormat format,
    QWidget* parent)
    : QOpenGLWidget(parent),
      projectRoot_(std::move(projectRoot)),
      userModelsRoot_(std::move(userModelsRoot)),
      modelPath_(std::move(modelPath)),
      format_(format) {
    setAttribute(Qt::WA_TranslucentBackground, true);
    setAttribute(Qt::WA_NoSystemBackground, true);
    setAttribute(Qt::WA_OpaquePaintEvent, false);
    setAutoFillBackground(false);
    setMouseTracking(true);

    renderTimer_.setTimerType(Qt::PreciseTimer);
    connect(&renderTimer_, &QTimer::timeout, this, QOverload<>::of(&Live2dGlWidget::update));
    setFramesPerSecond(120);
}

Live2dGlWidget::~Live2dGlWidget() {
    disposeRuntime();
}

void Live2dGlWidget::setFramesPerSecond(int fps) {
    fps = std::clamp(fps, 10, 240);
    renderTimer_.setInterval(std::max(1, qRound(1000.0 / fps)));
    if (isVisible()) {
        renderTimer_.start();
    }
}

void Live2dGlWidget::initializeGL() {
    auto* gl = context()->functions();
    gl->initializeOpenGLFunctions();
    context()->extraFunctions()->initializeOpenGLFunctions();
    gl->glDisable(GL_DEPTH_TEST);
    gl->glDisable(GL_DITHER);

    const QByteArray projectRoot = projectRoot_.toUtf8();
    const QByteArray userModelsRoot = userModelsRoot_.toUtf8();
    host_ = bandori_live2d_create(
        projectRoot.constData(),
        userModelsRoot.constData(),
        static_cast<std::uint32_t>(format_),
        static_cast<std::uint32_t>(std::max(width(), 1)),
        static_cast<std::uint32_t>(std::max(height(), 1)),
        &Live2dGlWidget::resolveGlProcedure,
        this);
    if (host_ == nullptr) {
        reportLastError("create");
        return;
    }

    const QByteArray modelPath = modelPath_.toUtf8();
    if (!bandori_live2d_load_model(
            host_,
            modelPath.constData(),
            static_cast<std::uint32_t>(std::max(width(), 1)),
            static_cast<std::uint32_t>(std::max(height(), 1)),
            1)) {
        reportLastError("load model");
        disposeRuntime();
        return;
    }
    if (format_ == ModelFormat::Moc3 && !bandori_live2d_set_scale(host_, 1.35)) {
        reportLastError("set Cubism 3 scale");
    }

    connect(
        context(),
        &QOpenGLContext::aboutToBeDestroyed,
        this,
        &Live2dGlWidget::disposeRuntime,
        Qt::DirectConnection);
    frameClock_.start();
    lastFrameMsec_ = 0;
    renderTimer_.start();
}

void Live2dGlWidget::resizeGL(int width, int height) {
    if (host_ == nullptr) {
        return;
    }
    const auto logicalWidth = static_cast<std::uint32_t>(std::max(width, 1));
    const auto logicalHeight = static_cast<std::uint32_t>(std::max(height, 1));
    if (!bandori_live2d_resize(host_, logicalWidth, logicalHeight)) {
        reportLastError("resize logical model");
        return;
    }
    if (format_ == ModelFormat::Moc3) {
        const qreal ratio = std::max<qreal>(devicePixelRatioF(), 1.0);
        const auto renderWidth = static_cast<std::uint32_t>(std::max(1, qRound(width * ratio)));
        const auto renderHeight = static_cast<std::uint32_t>(std::max(1, qRound(height * ratio)));
        if (!bandori_live2d_resize_renderer(host_, renderWidth, renderHeight)) {
            reportLastError("resize physical renderer");
        }
    }
}

void Live2dGlWidget::paintGL() {
    auto* gl = context()->functions();
    auto* extra = context()->extraFunctions();
    gl->glEnable(GL_BLEND);
    extra->glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD);
    gl->glClearColor(0.0F, 0.0F, 0.0F, 0.0F);
    gl->glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
    if (host_ == nullptr) {
        return;
    }

    const qint64 now = frameClock_.elapsed();
    const double delta = lastFrameMsec_ > 0
        ? std::clamp((now - lastFrameMsec_) / 1000.0, 0.0, 0.1)
        : 0.0;
    lastFrameMsec_ = now;
    if (!bandori_live2d_draw(host_, static_cast<double>(now), delta)) {
        reportLastError("draw frame");
        renderTimer_.stop();
    }
}

void Live2dGlWidget::mouseMoveEvent(QMouseEvent* event) {
    if (host_ != nullptr) {
        const QPointF position = event->position();
        if (!bandori_live2d_drag(host_, position.x(), position.y())) {
            reportLastError("update gaze");
        }
    }
    QOpenGLWidget::mouseMoveEvent(event);
}

std::uintptr_t Live2dGlWidget::resolveGlProcedure(const char* name, void*) {
    QOpenGLContext* context = QOpenGLContext::currentContext();
    if (context == nullptr || name == nullptr) {
        return 0;
    }
    const QFunctionPointer procedure = context->getProcAddress(QByteArray(name));
    return reinterpret_cast<std::uintptr_t>(procedure);
}

void Live2dGlWidget::disposeRuntime() {
    renderTimer_.stop();
    if (host_ == nullptr) {
        return;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    bandori_live2d_destroy(host_);
    host_ = nullptr;
    if (needsCurrent) {
        doneCurrent();
    }
}

void Live2dGlWidget::reportLastError(const char* operation) {
    qWarning().noquote() << "Live2D" << operation << "failed:" << bandori_live2d_last_error();
}

} // namespace bandori
