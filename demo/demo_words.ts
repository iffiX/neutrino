/**
 * The words the demo adds of its own, outside the panel's and the client's
 * catalogs, in both languages.
 */

const ENGLISH = "en";

const WORDS = {
  brand: ["微子·中枢", "Neutrino Hub"],
  page_title: ["微子中枢 示例", "Neutrino Hub demo"],
  sample_label: ["示例数据", "Sample data"],
  edition_switch: [
    "切换国内版和国际版",
    "Switch between the China and International editions",
  ],
  edition_cn: ["国内版", "China"],
  edition_intl: ["国际版", "International"],
  edition_cn_short: ["国内", "CN"],
  edition_intl_short: ["国际", "Intl"],
  side_switch: ["切换显示", "Switch sides"],
  side_panel: ["面板", "Panel"],
  side_client: ["客户端", "Client"],
  home: ["首页", "Home"],
  home_href: ["../", "../en/"],
  language_switch: ["切换语言", "Change language"],
  theme_switch: ["外观", "Appearance"],
  theme_to_dark: ["切换为深色模式", "Switch to dark mode"],
  theme_to_light: ["切换为浅色模式", "Switch to light mode"],
  panel_frame: ["中枢面板", "Hub panel"],
  client_frame: ["客户端", "Client"],
  loading: ["正在打开", "Opening"],
  refusal: [
    "这是演示，这一步不会真的执行。装上微子·中枢就能用。",
    "This is a demo, so this step does nothing. Install Neutrino Hub to use it.",
  ],
  open_notice: [
    "这是演示，装上微子·中枢就能打开。",
    "This is a demo. Install Neutrino Hub to open it.",
  ],
  panel_notice: [
    "这是演示，面板就在旁边。",
    "This is a demo. The panel is right beside this.",
  ],
  device_joined: ["{name} 已加入被控端。", "{name} joined the agents."],
  module_running: [
    "{title} 已运行，客户端的应用页多了它。",
    "{title} is running, and the client's Apps page now lists it.",
  ],
  client_joined: ["{name} 已加入。", "{name} joined."],
  new_machine: ["新机器", "New machine"],
  new_exit: ["新出口", "New exit"],
  ai_gateway: ["AI 网关", "AI gateway"],
  device_desktop: ["{device} 的桌面", "{device} desktop"],
  lab_hub_name: ["实验室中枢", "Lab hub"],
  lab_machine_name: ["实验室服务器", "Lab server"],
  shell_hint_linux: [
    "演示机器，试试 ls、nvidia-smi、top",
    "A demo machine. Try ls, nvidia-smi, top",
  ],
  shell_hint_windows: [
    "演示机器，试试 ls、cat notes.txt",
    "A demo machine. Try ls, cat notes.txt",
  ],
  shell_help: ["这台机器是演示，可以试试：", "This is a demo machine. Try:"],
  shell_quit_top: ["按 q 退出", "Press q to quit"],
  shell_model_idle: [
    "Hello! 这是演示机器，模型没有真的在跑。",
    "Hello! This is a demo machine, so no model really runs.",
  ],
  shell_python_only_version: [
    "这台机器是演示，这里只回答 python --version。",
    "This is a demo machine. Here it answers python --version only.",
  ],
  clipboard_sample: ["从手机粘贴的一行字", "A line pasted from the phone"],
} as const;

export type DemoWordKey = keyof typeof WORDS;

/**
 * One word in a language, Chinese for anything but English.
 *
 * Args:
 *   language: The language's code.
 *   key: The word's key.
 *   params: What fills the word's `{name}` marks.
 *
 * Returns:
 *   The word.
 */
export function demoWord(
  language: string,
  key: DemoWordKey,
  params: Record<string, string> = {},
): string {
  const [chinese, english] = WORDS[key];
  const word = language === ENGLISH ? english : chinese;
  return word.replace(
    /\{(\w+)\}/g,
    (_whole, name: string) => params[name] ?? "",
  );
}
