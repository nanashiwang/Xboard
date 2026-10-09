<?php

namespace App\Services;

use App\Utils\Helper;
use App\Models\User;

class ClientDownloadService
{
    public function catalog(): array
    {
        $manifest = collect(json_decode(file_get_contents(base_path('.docker/downloads/manifest.json')), true, 512, JSON_THROW_ON_ERROR))->keyBy('name');
        $package = function (string $name, string $label) use ($manifest): array {
            $asset = $manifest->get($name);
            return [
                'label' => $label,
                'url' => '/downloads/' . rawurlencode($name),
                'official_url' => $asset['url'],
                'sha256' => $asset['sha256'],
                'size' => round($asset['size'] / 1048576, 1) . ' MB',
            ];
        };
        $verge = [
            'id' => 'clash-verge', 'name' => 'Clash Verge Rev', 'version' => '2.4.7',
            'source' => 'https://github.com/clash-verge-rev/clash-verge-rev/tree/v2.4.7',
            'releases' => 'https://github.com/clash-verge-rev/clash-verge-rev/releases',
            'guide' => '安装后打开客户端，在本站点击“一键导入”。导入完成后，在客户端选择订阅并开启系统代理。',
        ];
        return [
            'windows' => $verge + [
                'platform' => 'Windows', 'requirement' => 'Windows 10 / 11 · 64 位',
                'packages' => [$package('Clash.Verge_2.4.7_x64-setup.exe', 'Windows x64 安装包')],
                'note' => 'Windows ARM 设备请到官方发布页选择对应安装包。',
            ],
            'macos' => $verge + [
                'platform' => 'macOS', 'requirement' => 'macOS 11 或更新版本',
                'packages' => [
                    $package('Clash.Verge_2.4.7_aarch64.dmg', 'Apple 芯片（M 系列）'),
                    $package('Clash.Verge_2.4.7_x64.dmg', 'Intel 芯片'),
                ],
                'note' => '在苹果菜单 → 关于本机中查看芯片，再选择对应安装包。',
            ],
            'android' => [
                'id' => 'clash-meta', 'name' => 'Clash Meta for Android', 'version' => '2.11.24',
                'platform' => 'Android', 'requirement' => 'Android 5.0+，建议 Android 7.0+',
                'source' => 'https://github.com/MetaCubeX/ClashMetaForAndroid/tree/v2.11.24',
                'releases' => 'https://github.com/MetaCubeX/ClashMetaForAndroid/releases',
                'packages' => [
                    $package('cmfa-2.11.24-meta-arm64-v8a-release.apk', 'ARM64（多数安卓手机）'),
                    $package('cmfa-2.11.24-meta-universal-release.apk', '通用版（不确定时选此项）'),
                ],
                'guide' => '安装并打开客户端，再回到浏览器点击“一键导入”。保存配置并选中它，然后启动连接。',
                'note' => '安卓电视、模拟器或旧设备可尝试通用版。安装时按系统提示操作。',
            ],
            'ios' => [
                'id' => 'sing-box', 'name' => 'sing-box', 'version' => 'App Store 版',
                'platform' => 'iPhone / iPad', 'requirement' => 'iOS / iPadOS 15 或更新版本',
                'source' => 'https://github.com/SagerNet/sing-box-for-apple',
                'packages' => [[
                    'label' => '前往 App Store 安装',
                    'url' => 'https://apps.apple.com/app/sing-box-mt/id6785326793',
                ]],
                'guide' => '从 App Store 安装并打开 sing-box，回到 Safari 点击“一键导入”。保存远程配置后，在客户端选择该配置并连接。',
                'note' => '官方要求使用中国大陆以外地区的 Apple 账户。是否可下载以所在地区 App Store 为准。',
            ],
            'linux' => $verge + [
                'platform' => 'Linux', 'requirement' => 'Debian / Ubuntu 系 · AMD64',
                'packages' => [$package('Clash.Verge_2.4.7_amd64.deb', 'Linux AMD64 · DEB')],
                'note' => '其他发行版和 ARM 设备请从官方发布页选择对应安装包。',
            ],
        ];
    }

    public function importData(User $user, string $client): array
    {
        $url = Helper::getSubscribeUrl($user->token);
        $name = rawurlencode((string) admin_setting('app_name', 'Xboard'));
        // Clash Verge reads everything after url= as the subscription URL.
        // Keep url last so a display name cannot become part of the token/query.
        $scheme = match ($client) {
            'clash-verge' => 'clash-verge://install-config?name=' . $name . '&url=' . rawurlencode($url),
            'clash-meta' => 'clashmeta://install-config?name=' . $name . '&url=' . rawurlencode($url),
            'sing-box' => 'sing-box://import-remote-profile?url=' . rawurlencode($url) . '#' . $name,
        };
        // Preserve the client's User-Agent: it selects the format and the
        // version-specific protocol capabilities in ClientController.
        return ['subscribe_url' => $url, 'import_url' => $scheme];
    }
}
