const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { DefinePlugin } = require('webpack');
const dotenv = require('dotenv');

// Lade .env falls vorhanden
dotenv.config();

module.exports = (env, argv) => {
  const isProd = argv.mode === 'production';

  return {
    entry: './ui-src/main.ts',
    mode: isProd ? 'production' : 'development',
    devtool: isProd ? 'source-map' : 'eval-source-map',
    output: {
      path: path.resolve(__dirname, 'www'),
      filename: 'bundle.[contenthash:8].js',
      clean: true,
      publicPath: ''
    },
    resolve: {
      extensions: ['.ts', '.js', '.json'],
      alias: {
        '@': path.resolve(__dirname, 'ui-src')
      }
    },
    module: {
      rules: [
        {
          test: /\.tsx?$/,
          use: [
            {
              loader: 'ts-loader',
              options: {
                transpileOnly: true
              }
            }
          ],
          exclude: /node_modules/
        },
        {
          test: /\.css$/,
          use: ['style-loader', 'css-loader']
        },
        {
          test: /\.(svg|png|jpg|jpeg|gif|webp)$/i,
          type: 'asset/resource',
          generator: {
            filename: 'assets/[name][ext]'
          }
        }
      ]
    },
    plugins: [
      new HtmlWebpackPlugin({
        template: './index.html',
        filename: 'index.html',
        inject: 'body'
      }),
      new DefinePlugin({
        'process.env.GEMINI_API_KEY': JSON.stringify(process.env.GEMINI_API_KEY || '')
      })
    ],
    devServer: {
      static: {
        directory: path.join(__dirname, 'www')
      },
      port: 4444,
      hot: true,
      open: false,
      historyApiFallback: true
    }
  };
};
