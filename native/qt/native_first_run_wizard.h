#pragma once

#include <QDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QList>
#include <QString>

class QLabel;
class QStackedWidget;
class QVBoxLayout;

namespace qfw {
class ComboBox;
class LineEdit;
class PrimaryPushButton;
class PushButton;
class SwitchButton;
}

namespace bandori {

class NativeFirstRunWizard final : public QDialog {
public:
    NativeFirstRunWizard(
        QString projectRoot,
        QString userModelsRoot,
        QJsonArray catalog,
        QJsonObject runtime,
        QWidget* parent = nullptr);

    QJsonObject nativeSettings() const;
    QJsonObject llmSettings() const;
    QJsonObject ttsSettings() const;

private:
    QWidget* createModelPackagePage();
    QWidget* createModelSelectionPage();
    QWidget* createAiPage();
    void setStep(int step);
    void updateStepStyle();
    void updateModelSelection(const QString& character = {});
    void selectBand(const QJsonObject& band);
    QJsonObject currentModel() const;
    void advance();
    void goBack();
    void openModelsFolder();

    QString projectRoot_;
    QString userModelsRoot_;
    QJsonArray catalog_;
    QJsonObject runtime_;
    QList<QLabel*> stepLabels_;
    QStackedWidget* stack_ = nullptr;
    qfw::PushButton* backButton_ = nullptr;
    qfw::PushButton* skipButton_ = nullptr;
    qfw::PrimaryPushButton* nextButton_ = nullptr;
    QLabel* modelStatusLabel_ = nullptr;
    QLabel* selectionHintLabel_ = nullptr;
    qfw::ComboBox* characterComboBox_ = nullptr;
    qfw::ComboBox* costumeComboBox_ = nullptr;
    qfw::LineEdit* llmApiUrlEdit_ = nullptr;
    qfw::LineEdit* llmApiKeyEdit_ = nullptr;
    qfw::LineEdit* llmModelEdit_ = nullptr;
    qfw::SwitchButton* ttsEnabledSwitch_ = nullptr;
    qfw::LineEdit* ttsApiUrlEdit_ = nullptr;
    int step_ = 0;
};

}  // namespace bandori
