#include "live2d_gl_widget.h"

#include <QByteArray>
#include <QDebug>
#include <QMouseEvent>
#include <QOpenGLContext>
#include <QOpenGLExtraFunctions>
#include <QOpenGLFramebufferObject>
#include <QOpenGLFramebufferObjectFormat>
#include <QOpenGLFunctions>
#include <QSurfaceFormat>

#include <algorithm>
#include <cmath>
#include <utility>

namespace bandori {

namespace {
constexpr int kMoc3BalancedSsaaScale = 2;
}

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

void Live2dGlWidget::setLipSyncMaxOpen(double value) {
    lipSyncMaxOpen_ = std::clamp(value, 0.0, 1.0);
    lipSyncTarget_ = std::clamp(lipSyncTarget_, 0.0, lipSyncMaxOpen_);
}

void Live2dGlWidget::setLipSyncPose(double level, double form) {
    lipSyncTarget_ = std::clamp(level, 0.0, lipSyncMaxOpen_);
    lipSyncFormTarget_ = std::clamp(form, -1.0, 1.0);
    lipSyncLastMsec_ = frameClock_.isValid() ? frameClock_.elapsed() : 0;
    update();
}

bool Live2dGlWidget::triggerAction(const QString& action, const QString& character) {
    if (host_ == nullptr || action.trimmed().isEmpty()) {
        return false;
    }
    const bool needsCurrent = context() != nullptr && QOpenGLContext::currentContext() != context();
    if (needsCurrent) {
        makeCurrent();
    }
    const QByteArray actionUtf8 = action.toUtf8();
    const QByteArray characterUtf8 = character.toUtf8();
    const bool triggered = bandori_live2d_trigger_action(
        host_, actionUtf8.constData(), characterUtf8.constData());
    if (!triggered) {
        reportLastError("trigger action");
    }
    if (needsCurrent) {
        doneCurrent();
    }
    if (triggered) {
        update();
    }
    return triggered;
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
        const QSize renderSize(
            std::max(1, qRound(width * ratio)) * kMoc3BalancedSsaaScale,
            std::max(1, qRound(height * ratio)) * kMoc3BalancedSsaaScale);
        rendererTargetSize_ = {};
        if (!syncRendererTarget(renderSize)) {
            reportLastError("resize physical renderer");
        }
    }
}

void Live2dGlWidget::paintGL() {
    const qreal ratio = std::max<qreal>(devicePixelRatioF(), 1.0);
    const QSize targetSize(
        std::max(1, qRound(width() * ratio)),
        std::max(1, qRound(height() * ratio)));
    if (host_ == nullptr) {
        clearTarget(targetSize);
        return;
    }

    bool usingSsaa = false;
    if (format_ == ModelFormat::Moc3) {
        const QSize ssaaSize = targetSize * kMoc3BalancedSsaaScale;
        usingSsaa = ensureSsaaFramebuffer(ssaaSize);
        const QSize renderSize = usingSsaa ? ssaaSize : targetSize;
        if (!syncRendererTarget(renderSize)) {
            reportLastError("synchronize renderer target");
            renderTimer_.stop();
            return;
        }
    }
    if (!usingSsaa) {
        context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
    }
    clearTarget(usingSsaa ? ssaaFramebufferSize_ : targetSize);

    const qint64 now = frameClock_.elapsed();
    const double delta = lastFrameMsec_ > 0
        ? std::clamp((now - lastFrameMsec_) / 1000.0, 0.0, 0.1)
        : 0.0;
    lastFrameMsec_ = now;
    const bool lipSyncFresh = now - lipSyncLastMsec_ <= 180;
    const double lipTarget = lipSyncFresh ? lipSyncTarget_ : 0.0;
    const double lipFormTarget = lipSyncFresh ? lipSyncFormTarget_ : 0.0;
    lipSyncLevel_ += (lipTarget - lipSyncLevel_) * 0.55;
    lipSyncForm_ += (lipFormTarget - lipSyncForm_) * 0.45;
    if (lipSyncLevel_ < 0.01) {
        lipSyncLevel_ = 0.0;
    }
    if (std::abs(lipSyncForm_) < 0.01) {
        lipSyncForm_ = 0.0;
    }
    if (!bandori_live2d_set_parameter(host_, "PARAM_MOUTH_OPEN_Y", lipSyncLevel_, 1.0)
        || !bandori_live2d_set_parameter(host_, "PARAM_MOUTH_FORM", lipSyncForm_, 1.0)) {
        if (usingSsaa) {
            ssaaFramebuffer_->release();
            context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
        }
        reportLastError("apply lip sync");
        renderTimer_.stop();
        return;
    }
    if (!bandori_live2d_draw(host_, static_cast<double>(now), delta)) {
        if (usingSsaa) {
            ssaaFramebuffer_->release();
            context()->extraFunctions()->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
        }
        reportLastError("draw frame");
        renderTimer_.stop();
        return;
    }
    if (usingSsaa) {
        ssaaFramebuffer_->release();
        if (!blitSsaaToDefault(targetSize)) {
            reportLastError("SSAA fallback render");
            renderTimer_.stop();
        }
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

bool Live2dGlWidget::ensureSsaaFramebuffer(const QSize& size) {
    if (ssaaFramebuffer_ == nullptr || ssaaFramebufferSize_ != size) {
        ssaaFramebuffer_.reset();
        QOpenGLFramebufferObjectFormat format;
        format.setAttachment(QOpenGLFramebufferObject::CombinedDepthStencil);
        format.setSamples(0);
        ssaaFramebuffer_ = std::make_unique<QOpenGLFramebufferObject>(size, format);
        ssaaFramebufferSize_ = size;
    }
    if (!ssaaFramebuffer_->isValid() || !ssaaFramebuffer_->bind()) {
        ssaaFramebuffer_.reset();
        ssaaFramebufferSize_ = {};
        return false;
    }
    return true;
}

bool Live2dGlWidget::syncRendererTarget(const QSize& size) {
    if (rendererTargetSize_ == size) {
        return true;
    }
    if (!bandori_live2d_resize_renderer(
            host_,
            static_cast<std::uint32_t>(size.width()),
            static_cast<std::uint32_t>(size.height()))) {
        return false;
    }
    rendererTargetSize_ = size;
    return true;
}

bool Live2dGlWidget::blitSsaaToDefault(const QSize& targetSize) {
    auto* gl = context()->functions();
    auto* extra = context()->extraFunctions();
    while (gl->glGetError() != GL_NO_ERROR) {
    }
    extra->glBindFramebuffer(GL_READ_FRAMEBUFFER, ssaaFramebuffer_->handle());
    extra->glBindFramebuffer(GL_DRAW_FRAMEBUFFER, defaultFramebufferObject());
    clearTarget(targetSize);
    extra->glBlitFramebuffer(
        0,
        0,
        ssaaFramebufferSize_.width(),
        ssaaFramebufferSize_.height(),
        0,
        0,
        targetSize.width(),
        targetSize.height(),
        GL_COLOR_BUFFER_BIT,
        GL_LINEAR);
    extra->glBindFramebuffer(GL_FRAMEBUFFER, defaultFramebufferObject());
    if (gl->glGetError() == GL_NO_ERROR) {
        return true;
    }

    // The simulation already advanced into the SSAA target. If the driver
    // cannot blit it, draw that exact state again at native resolution.
    ssaaFramebuffer_.reset();
    ssaaFramebufferSize_ = {};
    rendererTargetSize_ = {};
    if (!syncRendererTarget(targetSize)) {
        return false;
    }
    clearTarget(targetSize);
    return bandori_live2d_render_only(host_);
}

void Live2dGlWidget::clearTarget(const QSize& size) {
    auto* gl = context()->functions();
    auto* extra = context()->extraFunctions();
    gl->glViewport(0, 0, size.width(), size.height());
    gl->glEnable(GL_BLEND);
    extra->glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD);
    gl->glClearColor(0.0F, 0.0F, 0.0F, 0.0F);
    gl->glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
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
    ssaaFramebuffer_.reset();
    ssaaFramebufferSize_ = {};
    rendererTargetSize_ = {};
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
